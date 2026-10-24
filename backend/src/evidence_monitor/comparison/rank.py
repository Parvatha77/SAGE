"""Step 7: rank affected papers for each Case with transparent score components."""

import json
import logging
from sqlalchemy import select

from ..db import session_scope
from ..models import Case, Claim, Paper, Citation, AffectedItem

logger = logging.getLogger(__name__)

# Label severity weights (higher = more urgent)
LABEL_SEVERITY: dict[str, float] = {
    "retraction_impact": 40,
    "possible_reproducibility_concern": 30,
    "differs_in_context": 20,
    "extends": 10,
    "confirms": 5,
    "insufficient_information": 2,
    "unrelated": 0,
}

MAX_CITATION_SCORE = 20   # up to 20 points for citation count
MAX_RECENCY_SCORE = 20    # up to 20 points for recency
RELATION_SCORES = {
    "anchor": 20,
    "direct_citer": 15,
    "indirect": 5,
}


def _recency_score(year: int | None, base_year: int = 2018) -> float:
    if year is None:
        return 0.0
    return min(20.0, max(0.0, (year - base_year) * 2.0))


def _citation_score(cited_by_count: int | None) -> float:
    if cited_by_count is None:
        return 0.0
    return min(MAX_CITATION_SCORE, cited_by_count * 0.2)


def rank_case(case_id: str) -> list[AffectedItem]:
    """Compute and store AffectedItem rows for one Case."""
    with session_scope() as session:
        case = session.get(Case, case_id)
        anchor_claim = session.get(Claim, case.anchor_claim_id)
        anchor_paper = session.get(Paper, anchor_claim.paper_id)

        # Find direct citers of the anchor paper
        direct_citer_ids = session.execute(
            select(Citation.citing_id).where(Citation.cited_id == anchor_paper.id)
        ).scalars().all()

        # Collect all affected papers: anchor + direct citers
        affected_papers: list[tuple[str, str]] = [(anchor_paper.id, "anchor")]
        for cid in direct_citer_ids:
            affected_papers.append((cid, "direct_citer"))

        severity = LABEL_SEVERITY.get(case.label, 0)

        items = []
        for paper_id, relation in affected_papers:
            paper = session.get(Paper, paper_id)
            if paper is None:
                continue

            components = {
                "label_severity": severity,
                "relation": RELATION_SCORES.get(relation, 0),
                "citation_count": round(_citation_score(paper.cited_by_count), 2),
                "recency": round(_recency_score(paper.publication_year), 2),
            }
            total = sum(components.values())
            total = min(100.0, total)

            items.append(AffectedItem(
                case_id=case_id,
                paper_id=paper_id,
                score=round(total, 2),
                score_components_json=json.dumps(components),
                relation=relation,
            ))

        # Remove old items and re-insert
        old = session.execute(
            select(AffectedItem).where(AffectedItem.case_id == case_id)
        ).scalars().all()
        for o in old:
            session.delete(o)
        for item in items:
            session.add(item)

    return items


def rank_all(force: bool = False) -> int:
    """Rank affected papers for all Cases. Returns count processed."""
    with session_scope() as session:
        cases = session.execute(select(Case)).scalars().all()
        case_ids = [c.id for c in cases]

    processed = 0
    for case_id in case_ids:
        if not force:
            with session_scope() as session:
                existing = session.execute(
                    select(AffectedItem).where(AffectedItem.case_id == case_id).limit(1)
                ).scalar_one_or_none()
                if existing:
                    continue
        rank_case(case_id)
        processed += 1

    # Update priority_score on Case from the max AffectedItem score
    with session_scope() as session:
        for case_id in case_ids:
            items = session.execute(
                select(AffectedItem).where(AffectedItem.case_id == case_id)
            ).scalars().all()
            if items:
                case = session.get(Case, case_id)
                case.priority_score = max(i.score for i in items)

    return processed
