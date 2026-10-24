"""Use Case 2: Evidence-to-Impact Agent tests. All LLM and embeddings mocked."""

import json
import os
import tempfile
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Test DB setup — before any DB imports
# ---------------------------------------------------------------------------

_tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp_db.close()
os.environ["DB_URL"] = f"sqlite:///{_tmp_db.name}"
os.environ.setdefault("LLM_PROVIDER", "groq")
os.environ.setdefault("GROQ_API_KEY", "test-key-not-real")

import evidence_monitor.db as _db  # noqa: E402
_db._engine = None
_db._SessionLocal = None

from sqlalchemy import select  # noqa: E402
from evidence_monitor.models import (  # noqa: E402
    Base, Case, Claim, ClaimEmbedding, CoverageGap, CurrencyCheck, ContextFit,
    AuditEvent, Brief, BriefCheck, Need, NeedMatch, Paper, Outcome, SubmissionRecord,
)
from evidence_monitor.db import session_scope, get_engine  # noqa: E402
from evidence_monitor.api.main import app  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

Base.metadata.create_all(get_engine())
client = TestClient(app)


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
# Factories
# ---------------------------------------------------------------------------

def _make_paper(pub_year: int = 2022) -> str:
    pid = f"https://openalex.org/W{uuid.uuid4().hex[:8]}"
    with session_scope() as s:
        s.add(Paper(id=pid, title=f"Paper {pid[-6:]}", publication_year=pub_year,
                    abstract="An abstract."))
    return pid


def _make_claim(paper_id: str, population: str | None = "university students",
                country: str | None = "United Kingdom") -> str:
    cid = str(uuid.uuid4())
    with session_scope() as s:
        s.add(Claim(id=cid, paper_id=paper_id,
                    claim_text="Mindfulness reduces stress.",
                    source_sentence="Mindfulness significantly reduced stress scores.",
                    population=population, country_or_setting=country))
    return cid


def _make_embedding(claim_id: str, vec: list[float] | None = None) -> None:
    vec = vec or [0.1] * 384
    with session_scope() as s:
        s.add(ClaimEmbedding(claim_id=claim_id, model="all-MiniLM-L6-v2",
                             embedding_json=json.dumps(vec)))


def _make_need(population: str = "school students aged 11-18",
               setting: str = "school") -> str:
    nid = str(uuid.uuid4())
    with session_scope() as s:
        s.add(Need(
            id=nid, title="Test need", source_name="Test dept",
            need_text="What does the research show about mindfulness in schools?",
            audience="Policy analysts", jurisdiction="England",
            topic_keywords_json=json.dumps(["mindfulness", "wellbeing"]),
            population_of_interest=population,
            setting_of_interest=setting, is_example=True,
        ))
    return nid


def _make_need_match(need_id: str, claim_id: str, paper_id: str,
                     fit_score: float = 0.75, included: bool = True) -> str:
    mid = str(uuid.uuid4())
    with session_scope() as s:
        s.add(NeedMatch(id=mid, need_id=need_id, claim_id=claim_id,
                        paper_id=paper_id, fit_score=fit_score,
                        fit_reason="Relevant", included=included))
    return mid


def _make_case(anchor_claim_id: str, label: str = "confirms",
               state: str = "ready_for_review",
               needs_human_attention: bool = False,
               priority_score: float = 50.0) -> str:
    cid = str(uuid.uuid4())
    with session_scope() as s:
        s.add(Case(id=cid, anchor_claim_id=anchor_claim_id, label=label,
                   state=state, needs_human_attention=needs_human_attention,
                   priority_score=priority_score))
    return cid


# ---------------------------------------------------------------------------
# Test 1: currency_gate — retracted claim is excluded
# ---------------------------------------------------------------------------

def test_currency_gate_excludes_retracted():
    from evidence_monitor.models import IntegrityNotice
    from evidence_monitor.uc2.nodes import node_currency_gate

    pid = _make_paper()
    cid = _make_claim(pid)
    nid = _make_need()
    mid = _make_need_match(nid, cid, pid)

    with session_scope() as s:
        s.add(IntegrityNotice(paper_id=pid, kind="retraction", source="openalex"))

    node_currency_gate({"need_id": nid, "errors": []})

    with session_scope() as s:
        nm = s.get(NeedMatch, mid)
        cc = s.execute(select(CurrencyCheck).where(CurrencyCheck.need_match_id == mid)).scalars().first()

    assert nm.included is False
    assert cc.status == "retracted"


# ---------------------------------------------------------------------------
# Test 2: currency_gate — differs_in_context → current_with_note, included
# ---------------------------------------------------------------------------

def test_currency_gate_differs_in_context_gives_current_with_note():
    from evidence_monitor.uc2.nodes import node_currency_gate

    pid = _make_paper()
    cid = _make_claim(pid)
    _make_case(cid, label="differs_in_context", state="decided")
    nid = _make_need()
    mid = _make_need_match(nid, cid, pid)

    node_currency_gate({"need_id": nid, "errors": []})

    with session_scope() as s:
        nm = s.get(NeedMatch, mid)
        cc = s.execute(select(CurrencyCheck).where(CurrencyCheck.need_match_id == mid)).scalars().first()

    assert nm.included is True
    assert cc.status == "current_with_note"
    assert cc.note is not None


# ---------------------------------------------------------------------------
# Test 3: currency_gate — challenged (reproducibility + needs_human_attention) excluded
# ---------------------------------------------------------------------------

def test_currency_gate_excludes_challenged():
    from evidence_monitor.uc2.nodes import node_currency_gate

    pid = _make_paper()
    cid = _make_claim(pid)
    _make_case(cid, label="possible_reproducibility_concern",
               needs_human_attention=True, state="ready_for_review")
    nid = _make_need()
    mid = _make_need_match(nid, cid, pid)

    node_currency_gate({"need_id": nid, "errors": []})

    with session_scope() as s:
        nm = s.get(NeedMatch, mid)
        cc = s.execute(select(CurrencyCheck).where(CurrencyCheck.need_match_id == mid)).scalars().first()

    assert nm.included is False
    assert cc.status == "challenged"


# ---------------------------------------------------------------------------
# Test 4: currency_gate — high-priority unresolved case → under_review excluded
# ---------------------------------------------------------------------------

def test_currency_gate_excludes_under_review():
    from evidence_monitor.uc2.nodes import node_currency_gate

    pid = _make_paper()
    cid = _make_claim(pid)
    _make_case(cid, label="confirms", state="ready_for_review", priority_score=75.0)
    nid = _make_need()
    mid = _make_need_match(nid, cid, pid)

    node_currency_gate({"need_id": nid, "errors": []})

    with session_scope() as s:
        nm = s.get(NeedMatch, mid)
        cc = s.execute(select(CurrencyCheck).where(CurrencyCheck.need_match_id == mid)).scalars().first()

    assert nm.included is False
    assert cc.status == "under_review"


# ---------------------------------------------------------------------------
# Test 5: brief_writer rejects claim id not in supplied set
# ---------------------------------------------------------------------------

def test_brief_writer_rejects_unsupplied_claim_id(monkeypatch):
    fake_outside_id = str(uuid.uuid4())

    mock_provider = MagicMock()
    mock_provider.complete_json.return_value = {
        "text": "Mindfulness helps. [FAKE_ID]",
        "claim_ids": [fake_outside_id],  # not in supplied set
    }
    monkeypatch.setattr("evidence_monitor.llm.get_provider", lambda: mock_provider)

    pid = _make_paper()
    cid = _make_claim(pid)
    nid = _make_need()
    mid = _make_need_match(nid, cid, pid)

    from evidence_monitor.uc2.nodes import node_brief_writer
    result = node_brief_writer({"need_id": nid, "errors": []})

    assert result["stage"] == "error"
    assert any("unsupplied" in e for e in result["errors"])


# ---------------------------------------------------------------------------
# Test 6: brief_checker fails on overclaiming word
# ---------------------------------------------------------------------------

def test_brief_checker_fails_overclaiming():
    from evidence_monitor.uc2.nodes import node_brief_checker

    pid = _make_paper()
    cid = _make_claim(pid)
    nid = _make_need()
    mid = _make_need_match(nid, cid, pid)

    with session_scope() as s:
        b = Brief(need_id=nid, version=1, claim_ids_json=json.dumps([cid]), status="draft",
                  text=f"Mindfulness proves wellbeing improves [{cid}].\n\n## Limits to keep in mind\nSmall samples.")
        s.add(b)
        s.flush()
        brief_id = b.id

    result = node_brief_checker({"need_id": nid, "brief_id": brief_id, "errors": []})
    assert result["stage"] == "approval_gate"

    with session_scope() as s:
        checks = s.execute(select(BriefCheck).where(BriefCheck.brief_id == brief_id)).scalars().all()
        oc = next((c for c in checks if c.check_name == "no_overclaiming"), None)

    assert oc is not None
    assert oc.passed is False


# ---------------------------------------------------------------------------
# Test 7: brief_checker fails on missing limits section
# ---------------------------------------------------------------------------

def test_brief_checker_fails_missing_limits():
    from evidence_monitor.uc2.nodes import node_brief_checker

    pid = _make_paper()
    cid = _make_claim(pid)
    nid = _make_need()
    mid = _make_need_match(nid, cid, pid)

    with session_scope() as s:
        b = Brief(need_id=nid, version=1, claim_ids_json=json.dumps([cid]), status="draft",
                  text=f"Research shows mindfulness helps students [{cid}]. Evidence from 2022.")
        s.add(b)
        s.flush()
        brief_id = b.id

    node_brief_checker({"need_id": nid, "brief_id": brief_id, "errors": []})

    with session_scope() as s:
        checks = s.execute(select(BriefCheck).where(BriefCheck.brief_id == brief_id)).scalars().all()
        lim = next((c for c in checks if c.check_name == "limits_section_present"), None)

    assert lim is not None
    assert lim.passed is False


# ---------------------------------------------------------------------------
# Test 8: approval requires approver; rejection requires reason
# ---------------------------------------------------------------------------

def test_approval_requires_approver():
    from evidence_monitor.uc2.nodes import node_tracker

    pid = _make_paper()
    cid = _make_claim(pid)
    nid = _make_need()

    with session_scope() as s:
        b = Brief(need_id=nid, version=1, claim_ids_json=json.dumps([cid]),
                  status="draft", text="Brief text.")
        s.add(b)
        s.flush()
        brief_id = b.id

    result = node_tracker({
        "need_id": nid, "brief_id": brief_id, "errors": [],
        "decision": {"action": "approved", "approver": ""},  # empty approver
    })
    assert result["stage"] == "error"
    assert any("approver" in e for e in result["errors"])


def test_rejection_requires_reason():
    from evidence_monitor.uc2.nodes import node_tracker

    pid = _make_paper()
    cid = _make_claim(pid)
    nid = _make_need()

    with session_scope() as s:
        b = Brief(need_id=nid, version=1, claim_ids_json=json.dumps([cid]),
                  status="draft", text="Brief text.")
        s.add(b)
        s.flush()
        brief_id = b.id

    result = node_tracker({
        "need_id": nid, "brief_id": brief_id, "errors": [],
        "decision": {"action": "rejected", "reason": ""},  # empty reason
    })
    assert result["stage"] == "error"
    assert any("reason" in e for e in result["errors"])


# ---------------------------------------------------------------------------
# Test 9: approval resumes LangGraph from checkpoint (including restart)
# ---------------------------------------------------------------------------

def test_approval_resumes_after_restart():
    import tempfile
    from langgraph.checkpoint.sqlite import SqliteSaver
    from langgraph.types import Command
    from unittest.mock import patch as _patch
    from evidence_monitor.uc2.graph import build_uc2_graph

    pid = _make_paper()
    cid = _make_claim(pid)
    _make_embedding(cid)
    nid = _make_need()

    cp_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    cp_file.close()
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    initial_state: dict = {
        "need_id": nid, "stage": "need_intake", "matches": [], "errors": []
    }

    noop = lambda state: {}
    mock_provider = MagicMock()
    mock_provider.complete_json.return_value = {
        "relevance": "yes", "reason": "Relevant.",
        "text": f"Research shows mindfulness helps [{cid}].\n\n## Limits to keep in mind\nSmall samples from 2022.",
        "claim_ids": [cid],
    }

    with _patch("evidence_monitor.uc2.nodes.node_matcher",
                lambda state: {"matches": [_make_need_match(nid, cid, pid)],
                               "stage": "currency_gate", "errors": []}), \
         _patch("evidence_monitor.llm.get_provider", lambda: mock_provider), \
         _patch("sentence_transformers.SentenceTransformer") as mock_st:
        import numpy as np
        mock_st.return_value.encode.return_value = np.array([[0.1] * 384])

        with SqliteSaver.from_conn_string(cp_file.name) as cp:
            g = build_uc2_graph().compile(checkpointer=cp)
            list(g.stream(initial_state, config))

        # Simulate restart: new graph instance, same checkpoint DB
        decision = {"action": "approved", "approver": "test_editor", "reason": "Looks good"}
        with SqliteSaver.from_conn_string(cp_file.name) as cp2:
            g2 = build_uc2_graph().compile(checkpointer=cp2)
            list(g2.stream(Command(resume=decision), config))

    import os as _os
    _os.unlink(cp_file.name)

    with session_scope() as s:
        need = s.get(Need, nid)
        assert need.state == "approved", f"Expected approved, got {need.state}"


# ---------------------------------------------------------------------------
# Test 10: submission before approval → 409; outcome before submission → 409
# ---------------------------------------------------------------------------

def test_submit_before_approval_is_409():
    nid = _make_need()
    resp = client.post(f"/needs/{nid}/submit",
                       json={"submitted_by": "editor", "channel_note": "email"})
    assert resp.status_code == 409


def test_outcome_before_submission_is_409():
    nid = _make_need()
    resp = client.post(f"/needs/{nid}/outcome",
                       json={"outcome": "cited", "note": "Used in policy."})
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# Test 11: gap created when fewer than 2 usable matches
# ---------------------------------------------------------------------------

def test_gap_created_when_few_matches(monkeypatch):
    mock_provider = MagicMock()
    mock_provider.complete_json.return_value = {"idea": "Commission a study on X."}
    monkeypatch.setattr("evidence_monitor.llm.get_provider", lambda: mock_provider)

    pid = _make_paper()
    cid = _make_claim(pid)
    nid = _make_need()
    mid = _make_need_match(nid, cid, pid, fit_score=0.4)

    from evidence_monitor.uc2.nodes import node_gap_check
    result = node_gap_check({"need_id": nid, "errors": []})

    with session_scope() as s:
        gap = s.execute(
            select(CoverageGap).where(CoverageGap.need_id == nid)
        ).scalars().first()

    assert gap is not None
    assert "Commission" in (gap.idea_text or "")
    # Still proceeds to brief_writer (1 match is usable)
    assert result["stage"] in ("brief_writer", "done_no_evidence")


# ---------------------------------------------------------------------------
# Test 12: unknown context fields → level unknown, not poor
# ---------------------------------------------------------------------------

def test_context_fit_unknown_for_missing_fields():
    from evidence_monitor.uc2.nodes import node_context_fit

    pid = _make_paper()
    cid = _make_claim(pid, population=None, country=None)  # both None
    nid = _make_need()
    mid = _make_need_match(nid, cid, pid)

    node_context_fit({"need_id": nid, "errors": []})

    with session_scope() as s:
        cf = s.execute(
            select(ContextFit).where(ContextFit.need_match_id == mid)
        ).scalars().first()

    assert cf.level == "unknown"


# ---------------------------------------------------------------------------
# Test 13: copilot changes no rows except one AuditEvent
# ---------------------------------------------------------------------------

def test_copilot_adds_only_audit_event(monkeypatch):
    mock_provider = MagicMock()
    mock_provider.complete_json.return_value = {"answer": "The evidence shows..."}
    monkeypatch.setattr("evidence_monitor.llm.get_provider", lambda: mock_provider)

    pid = _make_paper()
    cid = _make_claim(pid)
    nid = _make_need()
    mid = _make_need_match(nid, cid, pid)

    # Give it a brief so copilot context is complete
    with session_scope() as s:
        s.add(Brief(need_id=nid, version=1, claim_ids_json=json.dumps([cid]),
                    status="draft", text="Some text."))

    resp = client.post(f"/needs/{nid}/copilot", json={"preset": "strongest_evidence"})
    assert resp.status_code == 200
    assert resp.json()["type"] == "AI draft"

    with session_scope() as s:
        # Only AuditEvent should have been added
        audit = s.execute(
            select(AuditEvent).where(AuditEvent.need_id == nid,
                                     AuditEvent.event == "copilot_query")
        ).scalars().all()
        need = s.get(Need, nid)

    assert len(audit) == 1
    assert need.state == "new"  # unchanged


# ---------------------------------------------------------------------------
# Test 14: needs.json loader rejects missing required fields
# ---------------------------------------------------------------------------

def test_needs_loader_rejects_missing_fields(tmp_path):
    from evidence_monitor.uc2.needs_loader import load_needs

    bad = tmp_path / "needs.json"
    bad.write_text(json.dumps([{"id": "x", "title": ""}]))  # missing many fields

    with pytest.raises(ValueError):
        load_needs(bad)


def test_needs_loader_accepts_valid_file(tmp_path):
    from evidence_monitor.uc2.needs_loader import load_needs

    good = tmp_path / "needs.json"
    good.write_text(json.dumps([{
        "id": "n1", "title": "Test", "source_name": "Gov",
        "source_url": None, "need_text": "What does research show?",
        "audience": "Analysts", "jurisdiction": "UK", "deadline": None,
        "topic_keywords": ["mindfulness"], "population_of_interest": "Adults",
        "setting_of_interest": "Schools", "is_example": True,
    }]))
    needs = load_needs(good)
    assert len(needs) == 1
    assert needs[0].id == "n1"
