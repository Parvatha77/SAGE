"""Step 3: field-by-field comparison of two claims."""

import logging
from pydantic import BaseModel
from sqlalchemy import select

from ..db import session_scope
from ..llm import get_provider
from ..models import Claim, ClaimPair, FieldComparison
from ..extraction.prompts import PROMPT_VERSION

logger = logging.getLogger(__name__)

COMPARE_VERSION = f"{PROMPT_VERSION}-cmp-v1"

TEXT_FIELDS = ["population", "country_or_setting", "design", "outcome_measure", "follow_up"]
NUM_FIELDS = ["sample_size"]

LABEL_SIMILAR = "similar"
LABEL_DIFFERS = "differs"
LABEL_UNKNOWN = "unknown"


class TextFieldResult(BaseModel):
    result: str  # similar / differs / unknown
    reason: str | None = None


_SYSTEM_TEXT = """\
Compare two field values from scientific abstracts. Output JSON:
{"result": "similar" | "differs" | "unknown", "reason": "one short sentence or null"}

Rules:
- If EITHER value is null/missing → "unknown". Never treat null as different from a real value.
- "similar" if they describe the same or closely comparable thing.
- "differs" only if both are present AND they describe clearly different things.
"""


def _compare_text_field(field: str, val_a: str | None, val_b: str | None) -> tuple[str, str | None]:
    if val_a is None or val_b is None:
        return LABEL_UNKNOWN, None
    if val_a.strip().lower() == val_b.strip().lower():
        return LABEL_SIMILAR, None

    provider = get_provider()
    try:
        raw = provider.complete_json(
            system=_SYSTEM_TEXT,
            user=f"Field: {field}\nValue A: {val_a}\nValue B: {val_b}",
            prompt_version=COMPARE_VERSION,
        )
        res = TextFieldResult.model_validate(raw)
        return res.result, res.reason
    except Exception as exc:
        logger.warning("Text field compare failed (%s): %s", field, exc)
        return LABEL_UNKNOWN, None


def _compare_sample_size(a: int | None, b: int | None) -> str:
    if a is None or b is None:
        return LABEL_UNKNOWN
    ratio = max(a, b) / max(min(a, b), 1)
    return LABEL_SIMILAR if ratio <= 3.0 else LABEL_DIFFERS


def compare_pair(pair_id: str) -> list[FieldComparison]:
    """Run field comparisons for one ClaimPair. Returns list of FieldComparison objects."""
    with session_scope() as session:
        pair = session.get(ClaimPair, pair_id)
        anchor = session.get(Claim, pair.anchor_claim_id)
        new = session.get(Claim, pair.new_claim_id)

        # Skip if already compared
        existing = session.execute(
            select(FieldComparison).where(FieldComparison.claim_pair_id == pair_id)
        ).scalars().all()
        if existing:
            return existing

    rows: list[FieldComparison] = []

    for field in TEXT_FIELDS:
        val_a = getattr(anchor, field)
        val_b = getattr(new, field)
        result, _ = _compare_text_field(field, val_a, val_b)
        rows.append(FieldComparison(
            claim_pair_id=pair_id,
            field_name=field,
            anchor_value=str(val_a) if val_a else None,
            new_value=str(val_b) if val_b else None,
            result=result,
        ))

    for field in NUM_FIELDS:
        val_a = getattr(anchor, field)
        val_b = getattr(new, field)
        result = _compare_sample_size(val_a, val_b)
        rows.append(FieldComparison(
            claim_pair_id=pair_id,
            field_name=field,
            anchor_value=str(val_a) if val_a is not None else None,
            new_value=str(val_b) if val_b is not None else None,
            result=result,
        ))

    with session_scope() as session:
        for row in rows:
            session.add(row)

    return rows


def compare_all(force: bool = False) -> int:
    """Run field comparisons for all relevant ClaimPairs. Returns count processed."""
    with session_scope() as session:
        pairs = session.execute(
            select(ClaimPair).where(
                ClaimPair.same_question.in_(["yes", "partly"])
            )
        ).scalars().all()
        pair_ids = [p.id for p in pairs]

    processed = 0
    for pair_id in pair_ids:
        if not force:
            with session_scope() as session:
                existing = session.execute(
                    select(FieldComparison).where(FieldComparison.claim_pair_id == pair_id)
                ).scalars().first()
                if existing:
                    continue
        compare_pair(pair_id)
        processed += 1
    return processed
