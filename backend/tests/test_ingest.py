"""Tests for ingest orchestration — no real network calls."""

import json
from pathlib import Path

import httpx
import pytest
import respx

from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import sessionmaker

from evidence_monitor.models import Base, Paper, Citation, IntegrityNotice

FIXTURES = Path(__file__).parent / "fixtures"


def _make_engine(tmp_path):
    url = f"sqlite:///{tmp_path}/test.db"
    engine = create_engine(url, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return engine


def _patch_db(monkeypatch, tmp_path):
    """Redirect db module to use an in-memory test database."""
    import evidence_monitor.db as db_mod
    import evidence_monitor.ingest as ingest_mod

    db_url = f"sqlite:///{tmp_path}/test.db"
    monkeypatch.setattr(db_mod.settings, "db_url", db_url)
    # Reset cached engine/session so new URL is picked up
    db_mod._engine = None
    db_mod._SessionLocal = None


# ---------------------------------------------------------------------------
# Upsert idempotency
# ---------------------------------------------------------------------------

@respx.mock
def test_upsert_idempotency(tmp_path, monkeypatch):
    """Ingesting the same search result twice must not create duplicate rows."""
    import evidence_monitor.sources.openalex as oa_mod
    import evidence_monitor.db as db_mod

    monkeypatch.setattr(oa_mod.settings, "cache_dir", tmp_path)
    monkeypatch.setattr(oa_mod.settings, "openalex_api_key", "")
    _patch_db(monkeypatch, tmp_path)

    payload = json.loads((FIXTURES / "openalex_search.json").read_text())
    respx.get("https://api.openalex.org/works").mock(
        return_value=httpx.Response(200, json=payload)
    )

    from evidence_monitor.ingest import ingest_topic

    r1 = ingest_topic("mindfulness", max_papers=10, refresh=True)
    # Second call hits the cache (no new HTTP) and must produce 0 new rows
    r2 = ingest_topic("mindfulness", max_papers=10)

    assert r1["papers_new"] == 1
    assert r2["papers_new"] == 0
    assert r2["papers_updated"] == 1  # existing row updated

    with db_mod.session_scope() as session:
        count = session.execute(select(func.count(Paper.id))).scalar()
    assert count == 1


# ---------------------------------------------------------------------------
# Citation linking
# ---------------------------------------------------------------------------

def test_citation_linking(tmp_path, monkeypatch):
    """Referenced works that are both in the DB get a Citation row."""
    import evidence_monitor.db as db_mod
    from evidence_monitor.ingest import _upsert_paper, _upsert_citation

    _patch_db(monkeypatch, tmp_path)
    db_mod.create_all()

    paper_a = {
        "id": "https://openalex.org/WA",
        "doi": None, "title": "Paper A", "abstract": None,
        "publication_date": "2020-01-01", "publication_year": 2020,
        "journal": None, "publisher": None, "authors": [],
        "referenced_works": [], "cited_by_count": 0,
        "type": "article", "is_retracted": False, "language": "en",
    }
    paper_b = {**paper_a, "id": "https://openalex.org/WB", "title": "Paper B"}

    with db_mod.session_scope() as session:
        _upsert_paper(session, paper_a)
        _upsert_paper(session, paper_b)
        new = _upsert_citation(session, paper_b["id"], paper_a["id"])
    assert new is True

    with db_mod.session_scope() as session:
        count = session.execute(select(func.count(Citation.id))).scalar()
    assert count == 1

    # Duplicate citation should not create a second row
    with db_mod.session_scope() as session:
        new2 = _upsert_citation(session, paper_b["id"], paper_a["id"])
    assert new2 is False

    with db_mod.session_scope() as session:
        count2 = session.execute(select(func.count(Citation.id))).scalar()
    assert count2 == 1


# ---------------------------------------------------------------------------
# Integrity notice from Crossref
# ---------------------------------------------------------------------------

@respx.mock
def test_integrity_check_creates_notice(tmp_path, monkeypatch):
    """check_integrity_all should create one retraction IntegrityNotice."""
    import evidence_monitor.db as db_mod
    import evidence_monitor.sources.openalex as oa_mod
    import evidence_monitor.sources.crossref as cr_mod

    monkeypatch.setattr(oa_mod.settings, "cache_dir", tmp_path)
    monkeypatch.setattr(cr_mod.settings, "cache_dir", tmp_path)
    monkeypatch.setattr(cr_mod.settings, "crossref_mailto", "test@test.com")
    _patch_db(monkeypatch, tmp_path)
    db_mod.create_all()

    doi = "10.1016/j.paid.2017.07.011"
    paper = Paper(
        id="https://openalex.org/W2741809807",
        doi=f"https://doi.org/{doi}",
        title="Mindfulness paper",
        openalex_is_retracted=False,
    )
    with db_mod.session_scope() as session:
        session.add(paper)

    payload = json.loads((FIXTURES / "crossref_retraction.json").read_text())
    respx.get(f"https://api.crossref.org/works/{doi}").mock(
        return_value=httpx.Response(200, json=payload)
    )

    from evidence_monitor.ingest import check_integrity_all
    result = check_integrity_all(refresh=True)

    assert result["notices_found"] == 1

    with db_mod.session_scope() as session:
        notice = session.execute(select(IntegrityNotice)).scalar_one()
    assert notice.kind == "retraction"
    assert notice.source == "crossref"


@respx.mock
def test_integrity_check_idempotent(tmp_path, monkeypatch):
    """Running check_integrity_all twice must not create duplicate notices."""
    import evidence_monitor.db as db_mod
    import evidence_monitor.sources.openalex as oa_mod
    import evidence_monitor.sources.crossref as cr_mod

    monkeypatch.setattr(oa_mod.settings, "cache_dir", tmp_path)
    monkeypatch.setattr(cr_mod.settings, "cache_dir", tmp_path)
    monkeypatch.setattr(cr_mod.settings, "crossref_mailto", "test@test.com")
    _patch_db(monkeypatch, tmp_path)
    db_mod.create_all()

    doi = "10.1016/j.paid.2017.07.011"
    paper = Paper(
        id="https://openalex.org/W2741809807",
        doi=f"https://doi.org/{doi}",
        title="Mindfulness paper",
        openalex_is_retracted=False,
    )
    with db_mod.session_scope() as session:
        session.add(paper)

    payload = json.loads((FIXTURES / "crossref_retraction.json").read_text())
    respx.get(f"https://api.crossref.org/works/{doi}").mock(
        return_value=httpx.Response(200, json=payload)
    )

    from evidence_monitor.ingest import check_integrity_all
    check_integrity_all(refresh=True)
    # Second run: Crossref cache is hit, and the notice already exists
    check_integrity_all()

    with db_mod.session_scope() as session:
        count = session.execute(select(func.count(IntegrityNotice.id))).scalar()
    assert count == 1
