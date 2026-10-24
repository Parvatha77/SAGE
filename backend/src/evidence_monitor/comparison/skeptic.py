"""Step 6: skeptic LLM call — challenge each Case label."""

import logging
from pydantic import BaseModel, field_validator
from sqlalchemy import select

from ..db import session_scope
from ..llm import get_provider
from ..models import Case, Claim
from ..extraction.prompts import PROMPT_VERSION
from .classify import VALID_LABELS

logger = logging.getLogger(__name__)

SKEPTIC_VERSION = f"{PROMPT_VERSION}-skp-v2"

VERDICTS = {"label stands", "label weakened", "change label"}


class SkepticResult(BaseModel):
    alternative_label: str
    contradicting_quote: str   # exact quoted sentence or "none found"
    argument: str
    verdict: str

    @field_validator("alternative_label")
    @classmethod
    def valid_label(cls, v: str) -> str:
        if v not in VALID_LABELS:
            raise ValueError(f"Invalid label: {v}")
        return v

    @field_validator("verdict")
    @classmethod
    def valid_verdict(cls, v: str) -> str:
        if v not in VERDICTS:
            raise ValueError(f"Invalid verdict: {v!r}")
        return v


_SYSTEM = """\
You are a skeptical peer reviewer. A classification system has assigned a label to the relationship between two scientific claims. Your job is to argue the STRONGEST alternative label — find the best case that the assigned label is wrong.

Output JSON only:
{
  "alternative_label": "<one of: confirms|extends|differs_in_context|possible_reproducibility_concern|retraction_impact|unrelated|insufficient_information>",
  "contradicting_quote": "<the strongest sentence from either source that contradicts the assigned label, copied exactly — or \"none found\" if nothing contradicts it>",
  "argument": "two sentences making the strongest case for the alternative",
  "verdict": "label stands" | "label weakened" | "change label"
}

RULES:
- "label weakened" or "change label" is ONLY allowed when contradicting_quote is a real quote (not "none found").
- If contradicting_quote is "none found", verdict MUST be "label stands".
- Be genuinely critical. If the assigned label is clearly correct, say "label stands".
"""


def _user_msg(case: Case, anchor: Claim, new: Claim | None) -> str:
    new_text = new.claim_text if new else "(no new claim — integrity notice case)"
    new_source = new.source_sentence if new else ""
    return (
        f"ASSIGNED LABEL: {case.label}\n"
        f"RATIONALE: {case.rationale}\n\n"
        f"ANCHOR CLAIM: {anchor.claim_text}\n"
        f"Source: {anchor.source_sentence}\n\n"
        f"NEW CLAIM: {new_text}\n"
        f"Source: {new_source}"
    )


def run_skeptic_all(force: bool = False) -> int:
    """Run skeptic on all Cases that don't have a verdict yet. Returns count processed."""
    with session_scope() as session:
        cases = session.execute(
            select(Case).where(Case.skeptic_verdict.is_(None))
        ).scalars().all()
        case_ids = [c.id for c in cases]

    provider = get_provider()
    processed = 0

    for case_id in case_ids:
        with session_scope() as session:
            case = session.get(Case, case_id)
            anchor = session.get(Claim, case.anchor_claim_id)
            new = session.get(Claim, case.new_claim_id) if case.new_claim_id else None

        try:
            raw = provider.complete_json(
                system=_SYSTEM,
                user=_user_msg(case, anchor, new),
                prompt_version=SKEPTIC_VERSION,
            )
            result = SkepticResult.model_validate(raw)
        except Exception as exc:
            logger.warning("Skeptic failed for case %s: %s", case_id, exc)
            continue

        # Enforce: "none found" quote → force "label stands"
        if result.contradicting_quote.strip().lower() == "none found":
            if result.verdict != "label stands":
                logger.debug(
                    "Skeptic overridden to 'label stands' (no quote) for case %s", case_id
                )
                result.verdict = "label stands"

        with session_scope() as session:
            case = session.get(Case, case_id)
            case.skeptic_verdict = result.verdict
            case.alternative_label = result.alternative_label
            # Store quote + argument together
            case.skeptic_argument = (
                f'Quote: "{result.contradicting_quote}" — {result.argument}'
                if result.contradicting_quote.lower() != "none found"
                else result.argument
            )
            # "change label" → flag for human review; do NOT overwrite the label
            if result.verdict == "change label":
                case.needs_human_attention = True

        processed += 1

    return processed
