"""Step 5: create retraction_impact Cases from IntegrityNotices (no LLM)."""

import logging
from sqlalchemy import select

from ..db import session_scope, create_all
from ..models import IntegrityNotice, Citation, Claim, Case, Paper
from ..extraction.prompts import PROMPT_VERSION

logger = logging.getLogger(__name__)

INTEGRITY_VERSION = f"{PROMPT_VERSION}-int-v1"


def build_integrity_cases() -> int:
    """
    For every IntegrityNotice, find papers that cite the affected paper
    and create a retraction_impact Case per (anchor_claim, citing_paper_claim) pair.
    Returns count of new Cases created.
    """
    create_all()
    created = 0

    with session_scope() as session:
        notices = session.execute(select(IntegrityNotice)).scalars().all()

    for notice in notices:
        # Find papers that cite the noticed paper
        with session_scope() as session:
            citers = session.execute(
                select(Citation.citing_id).where(Citation.cited_id == notice.paper_id)
            ).scalars().all()

            # Get claims from the noticed paper (anchor claims)
            anchor_claims = session.execute(
                select(Claim).where(Claim.paper_id == notice.paper_id)
            ).scalars().all()

        for anchor_claim in anchor_claims:
            for citing_paper_id in citers:
                with session_scope() as session:
                    # Avoid duplicates
                    existing = session.execute(
                        select(Case).where(
                            Case.anchor_claim_id == anchor_claim.id,
                            Case.notice_id == notice.id,
                            Case.prompt_version == INTEGRITY_VERSION,
                        )
                    ).scalar_one_or_none()
                    if existing:
                        continue

                    # Get a claim from the citing paper (if any)
                    citer_claim = session.execute(
                        select(Claim).where(Claim.paper_id == citing_paper_id).limit(1)
                    ).scalar_one_or_none()

                    session.add(Case(
                        anchor_claim_id=anchor_claim.id,
                        new_claim_id=citer_claim.id if citer_claim else None,
                        notice_id=notice.id,
                        label="retraction_impact",
                        rationale=(
                            f"Paper '{notice.paper_id}' has an integrity notice "
                            f"({notice.kind}) and is cited by paper '{citing_paper_id}'."
                        ),
                        confidence="high",
                        confidence_reason="Determined automatically from integrity notice data.",
                        prompt_version=INTEGRITY_VERSION,
                    ))
                    created += 1

    return created
