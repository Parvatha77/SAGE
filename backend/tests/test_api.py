"""Phase 4A API tests — all 9 required cases, LLM mocked."""

import json
import os
import tempfile
import uuid
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Test DB setup — runs BEFORE any module imports that touch the DB
# ---------------------------------------------------------------------------

_tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp_db.close()
os.environ["DB_URL"] = f"sqlite:///{_tmp_db.name}"
os.environ["LLM_PROVIDER"] = "groq"
os.environ["GROQ_API_KEY"] = "test-key-not-real"

import evidence_monitor.db as _db  # noqa: E402 — must come after env var set

# Force engine reset so it uses the test DB URL
_db._engine = None
_db._SessionLocal = None

from sqlalchemy import select  # noqa: E402
from evidence_monitor.models import Base, Case, Claim, Paper, AffectedItem, Decision, AuditEvent, RevisionItem  # noqa
from evidence_monitor.db import session_scope, get_engine  # noqa
from evidence_monitor.api.main import app  # noqa

# Create tables once
Base.metadata.create_all(get_engine())

client = TestClient(app)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clear_tables():
    """Truncate all rows between tests."""
    from sqlalchemy import text
    with get_engine().connect() as conn:
        for tbl in reversed(Base.metadata.sorted_tables):
            conn.execute(text(f"DELETE FROM {tbl.name}"))
        conn.commit()


@pytest.fixture(autouse=True)
def clean_db():
    _clear_tables()
    yield
    _clear_tables()


def _make_case(label="differs_in_context", priority=50.0, state="ready_for_review") -> str:
    """Insert a minimal Case with required Claim and Paper."""
    with session_scope() as s:
        paper_id = f"https://openalex.org/W{uuid.uuid4().hex[:8]}"
        s.add(Paper(id=paper_id, title="Test Paper"))
        claim_id = str(uuid.uuid4())
        s.add(Claim(id=claim_id, paper_id=paper_id,
                    claim_text="Test claim.", source_sentence="Test sentence."))
        case_id = str(uuid.uuid4())
        s.add(Case(id=case_id, anchor_claim_id=claim_id,
                   label=label, priority_score=priority, state=state))
    return case_id


# ---------------------------------------------------------------------------
# Test 1: Empty reason → 422
# ---------------------------------------------------------------------------

def test_empty_reason_is_422():
    case_id = _make_case()
    resp = client.post(f"/cases/{case_id}/decision", json={
        "action": "no_action",
        "reason": "",
        "decided_by": "editor1",
    })
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Test 2: Second decision → 409
# ---------------------------------------------------------------------------

def test_second_decision_is_409():
    case_id = _make_case()
    payload = {"action": "no_action", "reason": "Looks fine.", "decided_by": "editor1"}
    r1 = client.post(f"/cases/{case_id}/decision", json=payload)
    assert r1.status_code == 200
    r2 = client.post(f"/cases/{case_id}/decision", json=payload)
    assert r2.status_code == 409


# ---------------------------------------------------------------------------
# Test 3: Valid decision creates exactly one AuditEvent for decision_recorded
# ---------------------------------------------------------------------------

def test_valid_decision_creates_one_audit_event():
    case_id = _make_case()
    resp = client.post(f"/cases/{case_id}/decision", json={
        "action": "expert_review",
        "reason": "Needs expert eyes.",
        "decided_by": "editor2",
    })
    assert resp.status_code == 200

    detail = client.get(f"/cases/{case_id}").json()
    decision_events = [e for e in detail["audit_events"] if e["event"] == "decision_recorded"]
    assert len(decision_events) == 1


# ---------------------------------------------------------------------------
# Test 4: flag_for_update creates RevisionItems
# ---------------------------------------------------------------------------

def test_flag_for_update_creates_revision_items():
    case_id = _make_case()
    detail = client.get(f"/cases/{case_id}").json()
    paper_id = detail["anchor_claim"]["paper_id"]

    resp = client.post(f"/cases/{case_id}/decision", json={
        "action": "flag_for_update",
        "reason": "This paper needs updating.",
        "decided_by": "editor3",
        "flagged_paper_ids": [paper_id],
    })
    assert resp.status_code == 200

    rev = client.get("/revision-items").json()
    assert any(r["case_id"] == case_id for r in rev)


# ---------------------------------------------------------------------------
# Test 5: flag_for_update with no paper ids → 422
# ---------------------------------------------------------------------------

def test_flag_for_update_requires_paper_ids():
    case_id = _make_case()
    resp = client.post(f"/cases/{case_id}/decision", json={
        "action": "flag_for_update",
        "reason": "Missing paper ids.",
        "decided_by": "editor3",
        "flagged_paper_ids": [],
    })
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Test 6: Copilot does not change Case or Decision rows
# ---------------------------------------------------------------------------

def test_copilot_changes_no_case_or_decision(monkeypatch):
    case_id = _make_case()

    mock_provider = MagicMock()
    mock_provider.complete_json.return_value = {"answer": "Label assigned because contexts differ."}
    monkeypatch.setattr("evidence_monitor.llm.get_provider", lambda: mock_provider)

    resp = client.post(f"/cases/{case_id}/copilot", json={"preset": "why_label"})
    assert resp.status_code == 200
    assert resp.json()["type"] == "AI draft"

    detail = client.get(f"/cases/{case_id}").json()
    assert detail["state"] == "ready_for_review"
    assert detail["decision"] is None


# ---------------------------------------------------------------------------
# Test 7: Assessment treats unknown fields as "unknown"
# ---------------------------------------------------------------------------

def test_assessment_unknown_fields():
    case_id = _make_case()
    resp = client.get(f"/cases/{case_id}/assessment")
    assert resp.status_code == 200
    data = resp.json()
    # No FieldComparison rows → all field matches unknown
    assert data["population_match"] == "unknown"
    assert data["design_match"] == "unknown"
    assert data["outcome_match"] == "unknown"
    assert data["relative_sample_strength"] == "unknown"


# ---------------------------------------------------------------------------
# Test 8: /cases sorted by priority descending
# ---------------------------------------------------------------------------

def test_cases_sorted_by_priority():
    _make_case(priority=10.0)
    _make_case(priority=90.0)
    _make_case(priority=50.0)
    resp = client.get("/cases")
    assert resp.status_code == 200
    priorities = [c["priority_score"] for c in resp.json()]
    assert priorities == sorted(priorities, reverse=True)


# ---------------------------------------------------------------------------
# Test 9: Unrelated cases excluded from /cases list
# ---------------------------------------------------------------------------

def test_unrelated_cases_excluded_from_list():
    _make_case(label="unrelated")
    _make_case(label="extends")
    resp = client.get("/cases")
    assert resp.status_code == 200
    labels = [c["label"] for c in resp.json()]
    assert "unrelated" not in labels
    assert "extends" in labels


# ---------------------------------------------------------------------------
# Test 10: LangGraph resumes from review_gate and action node writes Decision
# ---------------------------------------------------------------------------

def test_langgraph_resume_writes_decision_and_audit():
    """action node writes exactly 1 Decision and 1 AuditEvent after resume."""
    import tempfile, os as _os
    from evidence_monitor.agent.graph import build_graph
    from langgraph.checkpoint.sqlite import SqliteSaver
    from langgraph.types import Command
    from unittest.mock import patch

    case_id = _make_case()
    cp_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    cp_file.close()
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    initial_state = {
        "case_id": case_id,
        "anchor_claim_id": None,
        "run_id": None,
        "stage": "discovery",
        "label": None,
        "confidence": None,
        "rationale": None,
        "skeptic_verdict": None,
        "needs_human_attention": False,
        "affected_items": [],
        "errors": [],
        "decision": None,
    }

    noop = lambda state: {}

    # Build graph INSIDE the patch context so compiled graph captures noop functions.
    # The graph pauses naturally at node_review_gate's interrupt() call.
    with patch("evidence_monitor.agent.nodes.node_discovery", noop), \
         patch("evidence_monitor.agent.nodes.node_evidence", noop), \
         patch("evidence_monitor.agent.nodes.node_integrity", noop), \
         patch("evidence_monitor.agent.nodes.node_skeptic", noop), \
         patch("evidence_monitor.agent.nodes.node_ranker", noop):

        with SqliteSaver.from_conn_string(cp_file.name) as cp:
            g = build_graph().compile(checkpointer=cp)
            list(g.stream(initial_state, config))

        # Resume: pass Command(resume=...) so interrupt() in node_review_gate
        # receives the decision payload as its return value.
        decision_payload = {
            "case_id": case_id,
            "action": "no_action",
            "reason": "Looks fine in context.",
            "decided_by": "test_editor",
            "flagged_paper_ids": [],
        }
        with SqliteSaver.from_conn_string(cp_file.name) as cp2:
            g2 = build_graph().compile(checkpointer=cp2)
            list(g2.stream(Command(resume=decision_payload), config))

    _os.unlink(cp_file.name)

    with session_scope() as s:
        decisions = s.execute(select(Decision).where(Decision.case_id == case_id)).scalars().all()
        assert len(decisions) == 1, f"Expected 1 Decision, got {len(decisions)}"
        assert decisions[0].action == "no_action"

        events = s.execute(
            select(AuditEvent).where(
                AuditEvent.case_id == case_id,
                AuditEvent.event == "decision_recorded",
            )
        ).scalars().all()
        assert len(events) == 1


# ---------------------------------------------------------------------------
# Test 11: Process restart between pause and resume still completes
# ---------------------------------------------------------------------------

def test_langgraph_resume_after_process_restart():
    """New graph instance with same checkpoint DB completes correctly."""
    import tempfile, os as _os
    from evidence_monitor.agent.graph import build_graph
    from langgraph.checkpoint.sqlite import SqliteSaver
    from langgraph.types import Command
    from unittest.mock import patch

    case_id = _make_case()
    cp_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    cp_file.close()
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    initial_state = {
        "case_id": case_id,
        "anchor_claim_id": None,
        "run_id": None,
        "stage": "discovery",
        "label": None,
        "confidence": None,
        "rationale": None,
        "skeptic_verdict": None,
        "needs_human_attention": False,
        "affected_items": [],
        "errors": [],
        "decision": None,
    }

    noop = lambda state: {}

    # First "process": build graph with noops, run until interrupt in review_gate
    with patch("evidence_monitor.agent.nodes.node_discovery", noop), \
         patch("evidence_monitor.agent.nodes.node_evidence", noop), \
         patch("evidence_monitor.agent.nodes.node_integrity", noop), \
         patch("evidence_monitor.agent.nodes.node_skeptic", noop), \
         patch("evidence_monitor.agent.nodes.node_ranker", noop):
        with SqliteSaver.from_conn_string(cp_file.name) as cp:
            g = build_graph().compile(checkpointer=cp)
            list(g.stream(initial_state, config))

    # Second "process": entirely new graph instance + same checkpoint DB
    decision_payload = {
        "case_id": case_id,
        "action": "expert_review",
        "reason": "Needs expert eyes.",
        "decided_by": "test_editor_2",
        "flagged_paper_ids": [],
    }
    with patch("evidence_monitor.agent.nodes.node_discovery", noop), \
         patch("evidence_monitor.agent.nodes.node_evidence", noop), \
         patch("evidence_monitor.agent.nodes.node_integrity", noop), \
         patch("evidence_monitor.agent.nodes.node_skeptic", noop), \
         patch("evidence_monitor.agent.nodes.node_ranker", noop):
        with SqliteSaver.from_conn_string(cp_file.name) as cp2:
            g2 = build_graph().compile(checkpointer=cp2)
            list(g2.stream(Command(resume=decision_payload), config))

    _os.unlink(cp_file.name)

    with session_scope() as s:
        dec = s.execute(select(Decision).where(Decision.case_id == case_id)).scalars().first()
        assert dec is not None, "Decision was not written after process restart + resume"
        assert dec.action == "expert_review"


# ---------------------------------------------------------------------------
# Test 12: Copilot includes source sentence in LLM context
# ---------------------------------------------------------------------------

def test_copilot_includes_source_sentence(monkeypatch):
    """The LLM prompt must contain the anchor claim's source_sentence."""
    captured = {}

    def mock_provider_factory():
        m = MagicMock()
        def capture_complete(system, user, **kwargs):
            captured["user"] = user
            return {"answer": "Because the contexts differ."}
        m.complete_json.side_effect = capture_complete
        return m

    monkeypatch.setattr("evidence_monitor.llm.get_provider", mock_provider_factory)

    with session_scope() as s:
        paper_id = f"https://openalex.org/W{uuid.uuid4().hex[:8]}"
        s.add(Paper(id=paper_id, title="Source Paper"))
        claim_id = str(uuid.uuid4())
        s.add(Claim(id=claim_id, paper_id=paper_id,
                    claim_text="Test claim.", source_sentence="UNIQUE_SOURCE_SENTENCE_FOR_TEST"))
        case_id = str(uuid.uuid4())
        s.add(Case(id=case_id, anchor_claim_id=claim_id, label="confirms", priority_score=50.0))

    resp = client.post(f"/cases/{case_id}/copilot", json={"preset": "why_label"})
    assert resp.status_code == 200
    assert "UNIQUE_SOURCE_SENTENCE_FOR_TEST" in captured.get("user", ""), \
        "Source sentence was not included in the LLM prompt"
