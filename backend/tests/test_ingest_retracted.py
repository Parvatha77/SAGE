"""Tests for ingest_retracted: mocked HTTP, no real network calls."""

import json
import os
import tempfile
import unittest
from unittest.mock import patch, MagicMock

import pytest

# ---------------------------------------------------------------------------
# Test DB setup — must happen before any imports that touch the DB
# ---------------------------------------------------------------------------

_tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp_db.close()
os.environ.setdefault("DB_URL", f"sqlite:///{_tmp_db.name}")
os.environ.setdefault("LLM_PROVIDER", "groq")
os.environ.setdefault("GROQ_API_KEY", "test-key-not-real")

import evidence_monitor.db as _db  # noqa: E402

_db._engine = None
_db._SessionLocal = None

from sqlalchemy import select  # noqa: E402
from evidence_monitor.models import Base, Paper, Citation, IntegrityNotice, IngestRun  # noqa: E402
from evidence_monitor.db import session_scope, get_engine  # noqa: E402

Base.metadata.create_all(get_engine())


def _clear():
    from sqlalchemy import text
    with get_engine().connect() as conn:
        for tbl in reversed(Base.metadata.sorted_tables):
            conn.execute(text(f"DELETE FROM {tbl.name}"))
        conn.commit()


@pytest.fixture(autouse=True)
def clean_db():
    _clear()
    yield
    _clear()


# ---------------------------------------------------------------------------
# Fake work factory
# ---------------------------------------------------------------------------

def _fake_work(openalex_id: str, is_retracted: bool = True, doi: str | None = None) -> dict:
    return {
        "id": openalex_id,
        "doi": doi,
        "title": f"Paper {openalex_id}",
        "abstract": "An abstract.",
        "publication_date": "2023-01-01",
        "publication_year": 2023,
        "journal": "Test Journal",
        "publisher": None,
        "authors": ["Author A"],
        "referenced_works": [],
        "cited_by_count": 3,
        "type": "article",
        "is_retracted": is_retracted,
        "language": "en",
    }


# ---------------------------------------------------------------------------
# Test 1: retracted papers are upserted into the DB
# ---------------------------------------------------------------------------

def test_ingest_retracted_upserts_papers():
    from evidence_monitor.ingest import ingest_retracted

    retracted = [_fake_work("https://openalex.org/W001", is_retracted=True)]

    with patch("evidence_monitor.sources.openalex.fetch_retracted_works", return_value=iter(retracted)), \
         patch("evidence_monitor.sources.openalex.get_citing_works", return_value=iter([])), \
         patch("evidence_monitor.sources.crossref.check_updates", return_value=[]):

        result = ingest_retracted("mindfulness", max_papers=1)

    assert result["status"] == "done"
    assert result["papers_new"] == 1

    with session_scope() as s:
        p = s.get(Paper, "https://openalex.org/W001")
        assert p is not None
        assert p.openalex_is_retracted is True


# ---------------------------------------------------------------------------
# Test 2: citing works are upserted and citations are linked
# ---------------------------------------------------------------------------

def test_ingest_retracted_upserts_citers_and_citations():
    from evidence_monitor.ingest import ingest_retracted

    retracted = [_fake_work("https://openalex.org/W002", is_retracted=True)]
    citer = _fake_work("https://openalex.org/W003", is_retracted=False)

    with patch("evidence_monitor.sources.openalex.fetch_retracted_works", return_value=iter(retracted)), \
         patch("evidence_monitor.sources.openalex.get_citing_works", return_value=iter([citer])), \
         patch("evidence_monitor.sources.crossref.check_updates", return_value=[]):

        result = ingest_retracted("ego depletion", max_papers=1)

    assert result["papers_new"] == 2  # retracted + citer
    assert result["citations_new"] == 1

    with session_scope() as s:
        citation = s.execute(
            select(Citation).where(
                Citation.citing_id == "https://openalex.org/W003",
                Citation.cited_id == "https://openalex.org/W002",
            )
        ).scalars().first()
        assert citation is not None


# ---------------------------------------------------------------------------
# Test 3: integrity check runs and notices are recorded
# ---------------------------------------------------------------------------

def test_ingest_retracted_records_integrity_notices():
    from evidence_monitor.ingest import ingest_retracted

    doi = "10.9999/test-retracted"
    retracted = [_fake_work("https://openalex.org/W004", is_retracted=True, doi=doi)]

    crossref_notice = {"kind": "retraction", "notice_doi": "10.9999/notice", "notice_date": "2024-01-01"}

    with patch("evidence_monitor.sources.openalex.fetch_retracted_works", return_value=iter(retracted)), \
         patch("evidence_monitor.sources.openalex.get_citing_works", return_value=iter([])), \
         patch("evidence_monitor.sources.crossref.check_updates", return_value=[crossref_notice]):

        result = ingest_retracted("retraction test", max_papers=1)

    assert result["notices_found"] >= 1

    with session_scope() as s:
        notices = s.execute(
            select(IntegrityNotice).where(IntegrityNotice.paper_id == "https://openalex.org/W004")
        ).scalars().all()
        kinds = {n.kind for n in notices}
        assert "retraction" in kinds


# ---------------------------------------------------------------------------
# Test 4: zero retracted papers found → no papers added, status still done
# ---------------------------------------------------------------------------

def test_ingest_retracted_handles_empty_results():
    from evidence_monitor.ingest import ingest_retracted

    with patch("evidence_monitor.sources.openalex.fetch_retracted_works", return_value=iter([])), \
         patch("evidence_monitor.sources.openalex.get_citing_works", return_value=iter([])), \
         patch("evidence_monitor.sources.crossref.check_updates", return_value=[]):

        result = ingest_retracted("nonexistent topic xyz", max_papers=5)

    assert result["status"] == "done"
    assert result["papers_new"] == 0
    assert result["citations_new"] == 0


# ---------------------------------------------------------------------------
# Test 5: get_citing_works failure is logged and skipped, not fatal
# ---------------------------------------------------------------------------

def test_ingest_retracted_survives_citer_fetch_failure():
    from evidence_monitor.ingest import ingest_retracted

    retracted = [_fake_work("https://openalex.org/W005", is_retracted=True)]

    with patch("evidence_monitor.sources.openalex.fetch_retracted_works", return_value=iter(retracted)), \
         patch("evidence_monitor.sources.openalex.get_citing_works", side_effect=RuntimeError("network error")), \
         patch("evidence_monitor.sources.crossref.check_updates", return_value=[]):

        result = ingest_retracted("topic", max_papers=1)

    # Retracted paper is still upserted; citer fetch failure is non-fatal
    assert result["status"] == "done"
    assert result["papers_new"] == 1
    assert result["citations_new"] == 0
