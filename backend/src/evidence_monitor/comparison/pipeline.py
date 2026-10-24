"""Step 8: orchestrates the full comparison pipeline."""

import logging

from .candidates import build_embeddings, find_candidates
from .relevance import check_relevance_all
from .compare import compare_all
from .classify import classify_all
from .integrity_cases import build_integrity_cases
from .skeptic import run_skeptic_all
from .rank import rank_all

logger = logging.getLogger(__name__)


def run_pipeline(limit: int | None = None, force: bool = False) -> dict:
    """
    Run the full Phase 3 pipeline end-to-end.

    Args:
        limit: cap on anchor claims processed in the candidate step.
        force: reprocess even already-done steps.
    """
    logger.info("Pipeline step 1: building embeddings")
    emb_created = build_embeddings(force=force)

    logger.info("Pipeline step 1b: finding candidates (limit=%s)", limit)
    pairs_new = find_candidates(limit=limit)

    logger.info("Pipeline step 2: relevance check")
    rel = check_relevance_all(force=force)

    logger.info("Pipeline step 3: field comparisons")
    cmp_count = compare_all(force=force)

    logger.info("Pipeline step 4: classification")
    cases_new = classify_all(force=force)

    logger.info("Pipeline step 5: integrity cases")
    integrity_new = build_integrity_cases()

    logger.info("Pipeline step 6: skeptic")
    skeptic_count = run_skeptic_all(force=force)

    logger.info("Pipeline step 7: ranking")
    ranked = rank_all(force=force)

    summary = {
        "embeddings_created": emb_created,
        "candidate_pairs_new": pairs_new,
        "relevance_checked": rel.get("checked", 0),
        "relevance_dropped": rel.get("dropped", 0),
        "comparisons_run": cmp_count,
        "cases_new": cases_new,
        "integrity_cases_new": integrity_new,
        "skeptic_run": skeptic_count,
        "ranked": ranked,
    }
    logger.info("Pipeline complete: %s", summary)
    return summary
