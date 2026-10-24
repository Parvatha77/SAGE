"""Step 4: LLM classification into one of five labels."""

import logging
from pydantic import BaseModel, field_validator
from sqlalchemy import select

from ..db import session_scope
from ..llm import get_provider
from ..models import Claim, ClaimPair, FieldComparison, Case
from ..extraction.prompts import PROMPT_VERSION
from .compare import LABEL_UNKNOWN

logger = logging.getLogger(__name__)

CLASSIFY_VERSION = f"{PROMPT_VERSION}-cls-v2"

VALID_LABELS = {
    "confirms", "extends", "differs_in_context",
    "possible_reproducibility_concern", "retraction_impact",
    "unrelated", "insufficient_information",
}


class ClassifyResult(BaseModel):
    label: str
    rationale: str
    confidence: str  # high / medium / low
    confidence_reason: str | None = None

    @field_validator("label")
    @classmethod
    def valid_label(cls, v: str) -> str:
        if v not in VALID_LABELS:
            raise ValueError(f"Invalid label: {v}")
        return v

    @field_validator("confidence")
    @classmethod
    def valid_confidence(cls, v: str) -> str:
        if v not in {"high", "medium", "low"}:
            raise ValueError(f"Invalid confidence: {v}")
        return v


_SYSTEM = """\
You are a research-evidence analyst. Given two empirical claims and a field comparison, choose the most accurate label for their relationship.

LABELS (use exactly one):
- confirms: same question, similar context, similar result.
- extends: same finding in a new method, setting, or population; result consistent.
- differs_in_context: result differs AND population/setting/method/follow-up also differ materially.
- possible_reproducibility_concern: result differs while population, design, and outcome measure are closely matched.
- retraction_impact: one paper has a retraction/correction and another relies on it.
- unrelated: claims do not address the same question.
- insufficient_information: not enough detail to assign any other label confidently.

RULES:
- Never claim a paper is wrong.
- Base the label only on the provided information. Null fields are unknown, not different.
- DIRECTION RULE: If both claims have the same direction and no field comparison shows "differs" for design or outcome_measure, do NOT use differs_in_context. Use confirms or extends instead.
- INSUFFICIENT_INFORMATION: Use this label ONLY when BOTH population AND design are unknown for at least one claim, OR when the outcome cannot be compared at all. If at least two compared fields are known and differ, use differs_in_context instead.
- Output JSON only.

OUTPUT FORMAT:
{"label": "...", "rationale": "two sentences max", "confidence": "high"|"medium"|"low", "confidence_reason": "one sentence or null"}
"""


def _user_msg(anchor: Claim, new: Claim, comparisons: list[FieldComparison]) -> str:
    field_lines = "\n".join(
        f"  {fc.field_name}: anchor={fc.anchor_value!r} | new={fc.new_value!r} | result={fc.result}"
        for fc in comparisons
    )
    anchor_dir = anchor.direction or "unknown"
    new_dir = new.direction or "unknown"
    same_direction = (anchor_dir == new_dir and anchor_dir != "unknown")
    direction_note = (
        f"DIRECTIONS MATCH ({anchor_dir}) — direction rule applies: "
        "do not use differs_in_context unless design or outcome_measure differs."
        if same_direction else
        f"DIRECTIONS: anchor={anchor_dir}, new={new_dir}"
    )
    return (
        f"ANCHOR CLAIM: {anchor.claim_text}\n"
        f"Direction: {anchor_dir}\n"
        f"Source: {anchor.source_sentence}\n\n"
        f"NEW CLAIM: {new.claim_text}\n"
        f"Direction: {new_dir}\n"
        f"Source: {new.source_sentence}\n\n"
        f"{direction_note}\n\n"
        f"FIELD COMPARISONS:\n{field_lines}"
    )


def _unknown_ratio(comparisons: list[FieldComparison]) -> float:
    if not comparisons:
        return 1.0
    n_unknown = sum(1 for fc in comparisons if fc.result == LABEL_UNKNOWN)
    return n_unknown / len(comparisons)


def _pre_llm_rules(
    anchor: Claim, new: Claim, comparisons: list[FieldComparison]
) -> str | None:
    """
    Apply deterministic rules BEFORE the LLM call.
    Returns a forced label string if a rule fires, else None.
    """
    # Direction rule: same direction + no design/outcome_measure differs → not differs_in_context
    # (enforced in the prompt; no pre-override needed — the LLM sees the rule explicitly)

    # Insufficient_information: only when BOTH population AND design are unknown for at least one claim
    # AND the outcome cannot be compared. If ≥2 known fields differ → use differs_in_context instead.
    cmp_by_field = {fc.field_name: fc.result for fc in comparisons}
    known_differs = sum(
        1 for r in cmp_by_field.values() if r == "differs"
    )
    if known_differs >= 2:
        # Enough signal — don't force insufficient_information
        return None

    anchor_pop_missing = not anchor.population
    anchor_design_missing = not anchor.design
    new_pop_missing = not new.population
    new_design_missing = not new.design

    both_unknown_for_one = (
        (anchor_pop_missing and anchor_design_missing) or
        (new_pop_missing and new_design_missing)
    )
    outcome_comparable = cmp_by_field.get("outcome_measure", "unknown") != "unknown"

    if both_unknown_for_one and not outcome_comparable:
        return "insufficient_information"

    return None


def classify_pair(pair_id: str, prompt_version: str = CLASSIFY_VERSION) -> ClassifyResult | None:
    """Classify one ClaimPair. Returns None if skipped or failed."""
    with session_scope() as session:
        pair = session.get(ClaimPair, pair_id)
        if pair.same_question == "no":
            return None
        anchor = session.get(Claim, pair.anchor_claim_id)
        new = session.get(Claim, pair.new_claim_id)
        comparisons = session.execute(
            select(FieldComparison).where(FieldComparison.claim_pair_id == pair_id)
        ).scalars().all()

    # Pre-LLM deterministic rules
    forced_label = _pre_llm_rules(anchor, new, list(comparisons))
    if forced_label:
        logger.debug("Pre-LLM rule forced label=%s for pair %s", forced_label, pair_id)
        return ClassifyResult(
            label=forced_label,
            rationale="Forced by pre-LLM rule: insufficient information to classify.",
            confidence="low",
            confidence_reason="Both population and design unknown for at least one claim, and outcome not comparable.",
        )

    provider = get_provider()
    try:
        raw = provider.complete_json(
            system=_SYSTEM,
            user=_user_msg(anchor, new, comparisons),
            prompt_version=prompt_version,
        )
        result = ClassifyResult.model_validate(raw)
    except Exception as exc:
        logger.warning("Classify failed for pair %s: %s", pair_id, exc)
        return None

    # Post-LLM rule: same direction + no design/outcome differs → can't be differs_in_context
    anchor_dir = anchor.direction or "unknown"
    new_dir = new.direction or "unknown"
    if (anchor_dir == new_dir and anchor_dir != "unknown"
            and result.label == "differs_in_context"):
        cmp_by_field = {fc.field_name: fc.result for fc in comparisons}
        design_differs = cmp_by_field.get("design") == "differs"
        outcome_differs = cmp_by_field.get("outcome_measure") == "differs"
        if not design_differs and not outcome_differs:
            logger.debug(
                "Direction rule: overriding differs_in_context → confirms for pair %s", pair_id
            )
            result.label = "confirms"
            result.confidence_reason = (
                "Direction rule applied: both claims have the same direction and "
                "no design or outcome_measure difference found."
            )

    # Rule: >50% unknown fields → cap confidence at low, force insufficient_information
    ratio = _unknown_ratio(comparisons)
    if ratio > 0.5:
        if result.confidence != "low":
            result.confidence_reason = (
                f"Capped to low: {ratio:.0%} of fields are unknown. "
                + (result.confidence_reason or "")
            )
            result.confidence = "low"
        if result.label not in {"unrelated", "insufficient_information"}:
            result.label = "insufficient_information"

    return result


def classify_all(force: bool = False) -> int:
    """Classify all relevant pairs that don't have a Case yet. Returns count created."""
    with session_scope() as session:
        pairs = session.execute(
            select(ClaimPair).where(
                ClaimPair.same_question.in_(["yes", "partly"])
            )
        ).scalars().all()
        pair_data = [(p.id, p.anchor_claim_id, p.new_claim_id) for p in pairs]

    created = 0
    for pair_id, anchor_id, new_id in pair_data:
        if not force:
            with session_scope() as session:
                existing = session.execute(
                    select(Case).where(
                        Case.anchor_claim_id == anchor_id,
                        Case.new_claim_id == new_id,
                        Case.prompt_version == CLASSIFY_VERSION,
                    )
                ).scalars().first()
                if existing:
                    continue

        result = classify_pair(pair_id, CLASSIFY_VERSION)
        if result is None:
            continue
        # Never create a Case for unrelated pairs
        if result.label == "unrelated":
            continue

        with session_scope() as session:
            session.add(Case(
                anchor_claim_id=anchor_id,
                new_claim_id=new_id,
                label=result.label,
                rationale=result.rationale,
                confidence=result.confidence,
                confidence_reason=result.confidence_reason,
                prompt_version=CLASSIFY_VERSION,
            ))
        created += 1

    return created
