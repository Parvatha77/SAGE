"""Batch runner: extract claims for all papers, with resume support."""

import json
import logging
from typing import Iterator

from sqlalchemy import select

from ..db import session_scope, create_all
from ..models import Paper, Claim, ExtractionRun
from .extractor import extract_claims
from .prompts import PROMPT_VERSION

logger = logging.getLogger(__name__)


def _already_extracted(session, paper_id: str) -> bool:
    row = session.execute(
        select(ExtractionRun).where(
            ExtractionRun.paper_id == paper_id,
            ExtractionRun.prompt_version == PROMPT_VERSION,
            ExtractionRun.status != "failed",
        )
    ).scalar_one_or_none()
    return row is not None


def run_extraction(
    limit: int | None = None,
    force: bool = False,
    paper_id: str | None = None,
) -> dict:
    """
    Extract claims for papers in the DB.

    Args:
        limit: max number of papers to process.
        force: re-extract even if already done.
        paper_id: process only this one paper.
    """
    create_all()

    with session_scope() as session:
        query = select(Paper).where(Paper.abstract.isnot(None))
        if paper_id:
            query = query.where(Paper.id == paper_id)
        papers = session.execute(query).scalars().all()

    counts = {"ok": 0, "empty": 0, "failed": 0, "skipped": 0}
    processed = 0

    for paper in papers:
        if limit is not None and processed >= limit:
            break

        with session_scope() as session:
            if not force and _already_extracted(session, paper.id):
                counts["skipped"] += 1
                continue

        if not paper.abstract:
            continue

        result = extract_claims(paper.abstract, paper.id)
        status = result["status"]
        counts[status] = counts.get(status, 0) + 1
        processed += 1

        with session_scope() as session:
            # Remove old extraction run for this paper+version if forcing
            if force:
                old_runs = session.execute(
                    select(ExtractionRun).where(
                        ExtractionRun.paper_id == paper.id,
                        ExtractionRun.prompt_version == PROMPT_VERSION,
                    )
                ).scalars().all()
                for r in old_runs:
                    # Delete associated claims
                    old_claims = session.execute(
                        select(Claim).where(
                            Claim.paper_id == paper.id,
                            Claim.prompt_version == PROMPT_VERSION,
                        )
                    ).scalars().all()
                    for c in old_claims:
                        session.delete(c)
                    session.delete(r)

            run = ExtractionRun(
                paper_id=paper.id,
                status=status,
                error=result.get("error"),
                input_tokens=result.get("input_tokens", 0),
                output_tokens=result.get("output_tokens", 0),
                cost_estimate=result.get("cost_estimate", 0.0),
                prompt_version=result.get("prompt_version"),
            )
            session.add(run)

            for claim in result.get("claims", []):
                session.add(Claim(
                    paper_id=paper.id,
                    claim_text=claim.claim_text,
                    source_sentence=claim.source_sentence,
                    direction=claim.direction,
                    effect_reported=claim.effect_reported,
                    population=claim.population,
                    country_or_setting=claim.country_or_setting,
                    design=claim.design,
                    outcome_measure=claim.outcome_measure,
                    sample_size=claim.sample_size,
                    sample_size_text=claim.sample_size_text,
                    follow_up=claim.follow_up,
                    is_primary_claim=claim.is_primary_claim,
                    extraction_confidence=claim.extraction_confidence,
                    confidence_note=claim.confidence_note,
                    fields_missing_json=json.dumps(claim.fields_missing),
                    model=result.get("model"),
                    prompt_version=result.get("prompt_version"),
                ))

        logger.info("Paper %s → %s", paper.id[-12:], status)

    return counts
