"""Step 2: LLM relevance check — do two claims address the same question?"""

import logging
from pydantic import BaseModel
from sqlalchemy import select

from ..db import session_scope
from ..llm import get_provider
from ..models import Claim, ClaimPair
from ..extraction.prompts import PROMPT_VERSION

logger = logging.getLogger(__name__)

RELEVANCE_VERSION = f"{PROMPT_VERSION}-rel-v1"


class RelevanceResult(BaseModel):
    same_question: str  # "yes" | "partly" | "no"
    reason: str


_SYSTEM = """\
You are a research-evidence analyst. Given two empirical claims from scientific abstracts, decide whether they address the same research question.

Same question means: the same or closely related intervention/exposure AND the same or closely related outcome measure.

Output JSON only:
{"same_question": "yes" | "partly" | "no", "reason": "one sentence"}
"""


def _user(a: Claim, b: Claim) -> str:
    return (
        f"CLAIM A: {a.claim_text}\n"
        f"Outcome: {a.outcome_measure or 'not reported'}\n\n"
        f"CLAIM B: {b.claim_text}\n"
        f"Outcome: {b.outcome_measure or 'not reported'}"
    )


def check_relevance_all(force: bool = False) -> dict:
    """Run relevance check on all ClaimPairs that don't have a decision yet."""
    provider = get_provider()
    checked = dropped = 0

    with session_scope() as session:
        pairs = session.execute(
            select(ClaimPair).where(ClaimPair.same_question.is_(None))
        ).scalars().all()
        pair_ids = [p.id for p in pairs]

    for pair_id in pair_ids:
        with session_scope() as session:
            pair = session.get(ClaimPair, pair_id)
            anchor = session.get(Claim, pair.anchor_claim_id)
            new = session.get(Claim, pair.new_claim_id)

        if not anchor or not new:
            continue

        try:
            raw = provider.complete_json(
                system=_SYSTEM,
                user=_user(anchor, new),
                prompt_version=RELEVANCE_VERSION,
            )
            result = RelevanceResult.model_validate(raw)
        except Exception as exc:
            logger.warning("Relevance check failed for pair %s: %s", pair_id, exc)
            continue

        with session_scope() as session:
            pair = session.get(ClaimPair, pair_id)
            pair.same_question = result.same_question
            pair.reason = result.reason
        checked += 1
        if result.same_question == "no":
            dropped += 1

    return {"checked": checked, "dropped": dropped}
