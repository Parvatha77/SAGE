"""Orchestration: search → upsert → cite → check integrity."""

import datetime
import json
import logging
import uuid
from typing import Any

from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy import select, func

from .db import session_scope, create_all
from .models import Paper, Citation, IntegrityNotice, IngestRun
from .sources import openalex as oa
from .sources import crossref as cr

logger = logging.getLogger(__name__)


def _upsert_paper(session, work: dict) -> tuple[bool, bool]:
    """Insert or update a Paper row. Returns (is_new, is_updated)."""
    existing = session.get(Paper, work["id"])
    now = datetime.datetime.now(datetime.UTC)
    data = {
        "id": work["id"],
        "doi": work.get("doi"),
        "title": work.get("title"),
        "abstract": work.get("abstract"),
        "publication_date": work.get("publication_date"),
        "publication_year": work.get("publication_year"),
        "journal": work.get("journal"),
        "publisher": work.get("publisher"),
        "authors_json": json.dumps(work.get("authors", [])),
        "cited_by_count": work.get("cited_by_count"),
        "type": work.get("type"),
        "language": work.get("language"),
        "openalex_is_retracted": work.get("is_retracted", False),
        "fetched_at": now,
    }
    if existing is None:
        session.add(Paper(**data))
        return True, False
    else:
        for k, v in data.items():
            setattr(existing, k, v)
        return False, True


def _upsert_citation(session, citing_id: str, cited_id: str) -> bool:
    """Insert a Citation if it doesn't exist. Returns True if new."""
    stmt = select(Citation).where(
        Citation.citing_id == citing_id,
        Citation.cited_id == cited_id,
    )
    existing = session.execute(stmt).scalar_one_or_none()
    if existing is None:
        session.add(Citation(citing_id=citing_id, cited_id=cited_id))
        return True
    return False


def ingest_topic(
    query: str,
    from_year: int | None = None,
    to_year: int | None = None,
    max_papers: int = 100,
    refresh: bool = False,
) -> dict:
    """Search OpenAlex, upsert papers, link citations among fetched papers."""
    create_all()
    run_id = str(uuid.uuid4())
    papers_new = papers_updated = citations_new = 0

    with session_scope() as session:
        run = IngestRun(id=run_id, query=query, status="running")
        session.add(run)

    try:
        works = list(oa.search_works(query, from_year, to_year, max_papers, refresh=refresh))
        fetched_ids = {w["id"] for w in works}

        with session_scope() as session:
            for work in works:
                is_new, is_updated = _upsert_paper(session, work)
                if is_new:
                    papers_new += 1
                elif is_updated:
                    papers_updated += 1

        # Link citations where both ends are in the DB
        with session_scope() as session:
            for work in works:
                for ref_id in work.get("referenced_works", []):
                    if ref_id in fetched_ids:
                        if _upsert_citation(session, work["id"], ref_id):
                            citations_new += 1

        status = "done"
    except Exception as exc:
        logger.error("ingest_topic failed: %s", exc)
        status = "error"

    with session_scope() as session:
        run = session.get(IngestRun, run_id)
        run.finished_at = datetime.datetime.now(datetime.UTC)
        run.papers_new = papers_new
        run.papers_updated = papers_updated
        run.citations_new = citations_new
        run.status = status

    return {
        "run_id": run_id,
        "papers_new": papers_new,
        "papers_updated": papers_updated,
        "citations_new": citations_new,
        "status": status,
    }


def ingest_new_citers(since_date: str | None = None, refresh: bool = False) -> dict:
    """For each paper in DB, fetch newer citing works and upsert them."""
    create_all()
    papers_new = papers_updated = citations_new = 0

    with session_scope() as session:
        paper_ids = [row[0] for row in session.execute(select(Paper.id))]

    for paper_id in paper_ids:
        try:
            citers = list(oa.get_citing_works(paper_id, since_date=since_date, refresh=refresh))
        except Exception as exc:
            logger.warning("get_citing_works failed for %s: %s", paper_id, exc)
            continue

        with session_scope() as session:
            for work in citers:
                is_new, is_updated = _upsert_paper(session, work)
                if is_new:
                    papers_new += 1
                elif is_updated:
                    papers_updated += 1
                if _upsert_citation(session, work["id"], paper_id):
                    citations_new += 1

    return {
        "papers_new": papers_new,
        "papers_updated": papers_updated,
        "citations_new": citations_new,
    }


def check_integrity_all(refresh: bool = False) -> dict:
    """Run Crossref checks for papers with DOIs not checked in the last 7 days."""
    create_all()
    stale_cutoff = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=7)
    notices_found = 0

    with session_scope() as session:
        papers = session.execute(select(Paper).where(Paper.doi.isnot(None))).scalars().all()

    for paper in papers:
        # Skip if checked recently
        with session_scope() as session:
            recent = session.execute(
                select(IntegrityNotice)
                .where(
                    IntegrityNotice.paper_id == paper.id,
                    IntegrityNotice.source == "crossref",
                    IntegrityNotice.checked_at > stale_cutoff,
                )
            ).scalar_one_or_none()
        if recent is not None:
            continue

        # Check Crossref
        try:
            notices = cr.check_updates(paper.doi, refresh=refresh)
        except Exception as exc:
            logger.warning("Crossref check failed for %s: %s", paper.doi, exc)
            notices = []

        with session_scope() as session:
            for notice in notices:
                exists = session.execute(
                    select(IntegrityNotice).where(
                        IntegrityNotice.paper_id == paper.id,
                        IntegrityNotice.kind == notice["kind"],
                        IntegrityNotice.source == "crossref",
                    )
                ).scalar_one_or_none()
                if exists is None:
                    session.add(IntegrityNotice(
                        paper_id=paper.id,
                        kind=notice["kind"],
                        notice_doi=notice.get("notice_doi"),
                        notice_date=notice.get("notice_date"),
                        source="crossref",
                    ))
                    notices_found += 1

            # Also record OpenAlex retraction flag
            p = session.get(Paper, paper.id)
            if p and p.openalex_is_retracted:
                oa_exists = session.execute(
                    select(IntegrityNotice).where(
                        IntegrityNotice.paper_id == paper.id,
                        IntegrityNotice.source == "openalex",
                        IntegrityNotice.kind == "retraction",
                    )
                ).scalar_one_or_none()
                if oa_exists is None:
                    session.add(IntegrityNotice(
                        paper_id=paper.id,
                        kind="retraction",
                        source="openalex",
                    ))
                    notices_found += 1

    return {"notices_found": notices_found}


def _check_integrity_for_ids(paper_ids: list[str], refresh: bool = False) -> int:
    """Run Crossref + OpenAlex integrity checks for a specific set of paper IDs only."""
    notices_found = 0
    with session_scope() as session:
        papers = [session.get(Paper, pid) for pid in paper_ids]
        papers = [p for p in papers if p and p.doi]

    for paper in papers:
        try:
            notices = cr.check_updates(paper.doi, refresh=refresh)
        except Exception as exc:
            logger.warning("Crossref check failed for %s: %s", paper.doi, exc)
            notices = []

        with session_scope() as session:
            for notice in notices:
                exists = session.execute(
                    select(IntegrityNotice).where(
                        IntegrityNotice.paper_id == paper.id,
                        IntegrityNotice.kind == notice["kind"],
                        IntegrityNotice.source == "crossref",
                    )
                ).scalar_one_or_none()
                if exists is None:
                    session.add(IntegrityNotice(
                        paper_id=paper.id,
                        kind=notice["kind"],
                        notice_doi=notice.get("notice_doi"),
                        notice_date=notice.get("notice_date"),
                        source="crossref",
                    ))
                    notices_found += 1

            p = session.get(Paper, paper.id)
            if p and p.openalex_is_retracted:
                oa_exists = session.execute(
                    select(IntegrityNotice).where(
                        IntegrityNotice.paper_id == paper.id,
                        IntegrityNotice.source == "openalex",
                        IntegrityNotice.kind == "retraction",
                    )
                ).scalar_one_or_none()
                if oa_exists is None:
                    session.add(IntegrityNotice(
                        paper_id=paper.id,
                        kind="retraction",
                        source="openalex",
                    ))
                    notices_found += 1

    return notices_found


def ingest_retracted(
    query: str,
    max_papers: int = 5,
    refresh: bool = False,
) -> dict:
    """Fetch retracted works matching *query*, upsert them + their citers, then check integrity."""
    create_all()
    run_id = str(uuid.uuid4())
    papers_new = papers_updated = citations_new = 0

    with session_scope() as session:
        run = IngestRun(id=run_id, query=f"retracted:{query}", status="running")
        session.add(run)

    retracted_ids: set[str] = set()
    try:
        retracted = list(oa.fetch_retracted_works(query, max_papers, refresh=refresh))
        retracted_ids = {w["id"] for w in retracted}

        with session_scope() as session:
            for work in retracted:
                is_new, is_updated = _upsert_paper(session, work)
                if is_new:
                    papers_new += 1
                elif is_updated:
                    papers_updated += 1

        # Fetch citing works for each retracted paper
        for paper_id in retracted_ids:
            try:
                citers = list(oa.get_citing_works(paper_id, refresh=refresh))
            except Exception as exc:
                logger.warning("get_citing_works failed for %s: %s", paper_id, exc)
                citers = []

            with session_scope() as session:
                for work in citers:
                    is_new, is_updated = _upsert_paper(session, work)
                    if is_new:
                        papers_new += 1
                    elif is_updated:
                        papers_updated += 1
                    if _upsert_citation(session, work["id"], paper_id):
                        citations_new += 1

        status = "done"
    except Exception as exc:
        logger.error("ingest_retracted failed: %s", exc)
        status = "error"

    with session_scope() as session:
        run = session.get(IngestRun, run_id)
        run.finished_at = datetime.datetime.now(datetime.UTC)
        run.papers_new = papers_new
        run.papers_updated = papers_updated
        run.citations_new = citations_new
        run.status = status

    # Only check integrity for the retracted papers we just fetched, not all papers.
    notices_found = _check_integrity_for_ids(list(retracted_ids), refresh=refresh)

    return {
        "run_id": run_id,
        "papers_new": papers_new,
        "papers_updated": papers_updated,
        "citations_new": citations_new,
        "notices_found": notices_found,
        "status": status,
    }


def get_stats() -> dict:
    """Return row counts and last 5 IngestRuns."""
    create_all()
    with session_scope() as session:
        counts = {
            "papers": session.execute(select(func.count(Paper.id))).scalar(),
            "citations": session.execute(select(func.count(Citation.id))).scalar(),
            "integrity_notices": session.execute(select(func.count(IntegrityNotice.id))).scalar(),
            "ingest_runs": session.execute(select(func.count(IngestRun.id))).scalar(),
        }
        recent_runs = (
            session.execute(
                select(IngestRun).order_by(IngestRun.started_at.desc()).limit(5)
            )
            .scalars()
            .all()
        )
        runs_data = [
            {
                "id": r.id[:8],
                "query": r.query,
                "status": r.status,
                "papers_new": r.papers_new,
                "started_at": str(r.started_at)[:19],
            }
            for r in recent_runs
        ]
    return {"counts": counts, "recent_runs": runs_data}
