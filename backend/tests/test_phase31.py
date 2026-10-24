"""Phase 3.1: label-quality rule tests."""

import json
import os
import tempfile
import uuid
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Test DB setup
# ---------------------------------------------------------------------------

_tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp_db.close()
os.environ["DB_URL"] = f"sqlite:///{_tmp_db.name}"
os.environ.setdefault("LLM_PROVIDER", "groq")
os.environ.setdefault("GROQ_API_KEY", "test-key-not-real")

import evidence_monitor.db as _db
_db._engine = None
_db._SessionLocal = None

from sqlalchemy import select
from evidence_monitor.models import (
    Base, Case, Claim, ClaimEmbedding, ClaimPair, FieldComparison, Paper,
)
from evidence_monitor.db import session_scope, get_engine

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


def _paper(pub_year: int = 2022, paper_id: str | None = None) -> str:
    pid = paper_id or f"https://openalex.org/W{uuid.uuid4().hex[:8]}"
    with session_scope() as s:
        s.add(Paper(id=pid, title=f"Paper {pid[-6:]}", publication_year=pub_year))
    return pid


def _claim(paper_id: str, population: str | None = "students",
           design: str | None = "RCT", direction: str | None = "positive",
           source: str | None = None) -> str:
    cid = str(uuid.uuid4())
    with session_scope() as s:
        s.add(Claim(
            id=cid, paper_id=paper_id,
            claim_text="Mindfulness reduces stress.",
            source_sentence=source or f"Mindfulness reduced stress in {paper_id[-4:]}.",
            population=population, design=design, direction=direction,
        ))
    return cid


def _pair(anchor_id: str, new_id: str, same_question: str = "yes") -> str:
    pid = str(uuid.uuid4())
    with session_scope() as s:
        s.add(ClaimPair(id=pid, anchor_claim_id=anchor_id,
                        new_claim_id=new_id, same_question=same_question))
    return pid


def _fc(pair_id: str, field: str, result: str,
        anchor_val: str = "X", new_val: str = "Y") -> None:
    with session_scope() as s:
        s.add(FieldComparison(claim_pair_id=pair_id, field_name=field,
                              anchor_value=anchor_val, new_value=new_val, result=result))


# ---------------------------------------------------------------------------
# Test 1: same-paper guard — no pair created for claims from the same paper
# ---------------------------------------------------------------------------

def test_same_paper_no_candidate_pair():
    from evidence_monitor.comparison.candidates import find_candidates, build_embeddings

    pid = _paper()
    c1 = _claim(pid)
    c2 = _claim(pid)

    # Build embeddings
    with session_scope() as s:
        for cid in [c1, c2]:
            s.add(ClaimEmbedding(claim_id=cid, model="test",
                                 embedding_json=json.dumps([0.1] * 384)))

    pairs = find_candidates()
    # No pair should be created between same-paper claims
    with session_scope() as s:
        all_pairs = s.execute(select(ClaimPair)).scalars().all()
    assert all(
        not (p.anchor_claim_id in [c1, c2] and p.new_claim_id in [c1, c2])
        for p in all_pairs
    ), "Same-paper pair should not be created"


# ---------------------------------------------------------------------------
# Test 2: overlapping source sentences (Jaccard >= 0.7) → no pair
# ---------------------------------------------------------------------------

def test_overlapping_source_sentence_skipped():
    from evidence_monitor.comparison.candidates import find_candidates

    p1 = _paper(2021)
    p2 = _paper(2022)
    shared_src = "Mindfulness reduced anxiety stress depression wellbeing outcomes significantly."
    c1 = _claim(p1, source=shared_src)
    c2 = _claim(p2, source=shared_src)  # identical → Jaccard = 1.0

    with session_scope() as s:
        for cid in [c1, c2]:
            s.add(ClaimEmbedding(claim_id=cid, model="test",
                                 embedding_json=json.dumps([0.5] * 384)))

    find_candidates()
    with session_scope() as s:
        pairs = s.execute(select(ClaimPair)).scalars().all()
    assert len(pairs) == 0, "High-overlap source sentence should be skipped"


# ---------------------------------------------------------------------------
# Test 3: direction rule — same direction + no design/outcome differs → confirms
# ---------------------------------------------------------------------------

def test_direction_rule_overrides_differs_in_context(monkeypatch):
    from evidence_monitor.comparison.classify import classify_pair, CLASSIFY_VERSION

    mock_provider = MagicMock()
    # LLM returns differs_in_context, but direction rule should override to confirms
    mock_provider.complete_json.return_value = {
        "label": "differs_in_context",
        "rationale": "Contexts appear to differ.",
        "confidence": "medium",
        "confidence_reason": None,
    }
    monkeypatch.setattr("evidence_monitor.comparison.classify.get_provider", lambda: mock_provider)

    p1, p2 = _paper(2020), _paper(2022)
    c1 = _claim(p1, direction="positive")
    c2 = _claim(p2, direction="positive")
    pair_id = _pair(c1, c2)
    _fc(pair_id, "population", "similar", "students", "students")
    _fc(pair_id, "design", "similar", "RCT", "RCT")  # no differs

    result = classify_pair(pair_id, CLASSIFY_VERSION)
    assert result is not None
    assert result.label == "confirms", (
        f"Direction rule should override differs_in_context to confirms, got {result.label}"
    )


# ---------------------------------------------------------------------------
# Test 4: direction rule — design differs → differs_in_context allowed
# ---------------------------------------------------------------------------

def test_direction_rule_allows_differs_when_design_differs(monkeypatch):
    from evidence_monitor.comparison.classify import classify_pair, CLASSIFY_VERSION

    mock_provider = MagicMock()
    mock_provider.complete_json.return_value = {
        "label": "differs_in_context",
        "rationale": "Design differs.",
        "confidence": "medium",
        "confidence_reason": None,
    }
    monkeypatch.setattr("evidence_monitor.comparison.classify.get_provider", lambda: mock_provider)

    p1, p2 = _paper(2020), _paper(2022)
    c1 = _claim(p1, direction="positive")
    c2 = _claim(p2, direction="positive")
    pair_id = _pair(c1, c2)
    _fc(pair_id, "design", "differs", "RCT", "observational")  # design differs

    result = classify_pair(pair_id, CLASSIFY_VERSION)
    assert result is not None
    assert result.label == "differs_in_context"


# ---------------------------------------------------------------------------
# Test 5: insufficient_information — both pop and design unknown for one claim
# ---------------------------------------------------------------------------

def test_insufficient_information_forced_when_both_unknown(monkeypatch):
    from evidence_monitor.comparison.classify import classify_pair, CLASSIFY_VERSION

    # LLM would return something else, but pre-LLM rule should force insufficient_information
    mock_provider = MagicMock()
    mock_provider.complete_json.return_value = {
        "label": "confirms",
        "rationale": "Seems to confirm.",
        "confidence": "medium",
        "confidence_reason": None,
    }
    monkeypatch.setattr("evidence_monitor.comparison.classify.get_provider", lambda: mock_provider)

    p1, p2 = _paper(2020), _paper(2022)
    c1 = _claim(p1, population=None, design=None)  # both unknown
    c2 = _claim(p2)
    pair_id = _pair(c1, c2)
    _fc(pair_id, "outcome_measure", "unknown")  # outcome not comparable either

    result = classify_pair(pair_id, CLASSIFY_VERSION)
    assert result is not None
    assert result.label == "insufficient_information"
    # LLM should NOT have been called (pre-LLM rule fired)
    mock_provider.complete_json.assert_not_called()


# ---------------------------------------------------------------------------
# Test 6: insufficient_information NOT forced when ≥2 known fields differ
# ---------------------------------------------------------------------------

def test_insufficient_information_not_forced_with_known_diffs(monkeypatch):
    from evidence_monitor.comparison.classify import classify_pair, CLASSIFY_VERSION

    mock_provider = MagicMock()
    mock_provider.complete_json.return_value = {
        "label": "differs_in_context",
        "rationale": "Contexts differ.",
        "confidence": "medium",
        "confidence_reason": None,
    }
    monkeypatch.setattr("evidence_monitor.comparison.classify.get_provider", lambda: mock_provider)

    p1, p2 = _paper(2020), _paper(2022)
    c1 = _claim(p1, population=None, design=None)  # unknown
    c2 = _claim(p2)
    pair_id = _pair(c1, c2)
    # Two known diffs → rule doesn't fire
    _fc(pair_id, "population", "differs", "adults", "children")
    _fc(pair_id, "design", "differs", "RCT", "survey")

    result = classify_pair(pair_id, CLASSIFY_VERSION)
    assert result is not None
    assert result.label != "insufficient_information"


# ---------------------------------------------------------------------------
# Test 7: unrelated pairs → no Case created
# ---------------------------------------------------------------------------

def test_unrelated_not_stored(monkeypatch):
    from evidence_monitor.comparison.classify import classify_all, CLASSIFY_VERSION

    mock_provider = MagicMock()
    mock_provider.complete_json.return_value = {
        "label": "unrelated",
        "rationale": "Different topics entirely.",
        "confidence": "high",
        "confidence_reason": None,
    }
    monkeypatch.setattr("evidence_monitor.comparison.classify.get_provider", lambda: mock_provider)

    p1, p2 = _paper(2020), _paper(2022)
    c1 = _claim(p1)
    c2 = _claim(p2)
    _pair(c1, c2, same_question="partly")

    count = classify_all(force=True)
    with session_scope() as s:
        cases = s.execute(select(Case)).scalars().all()

    assert len(cases) == 0, "Unrelated pairs should not create Cases"


# ---------------------------------------------------------------------------
# Test 8: skeptic — "none found" quote forces "label stands"
# ---------------------------------------------------------------------------

def test_skeptic_none_found_forces_label_stands(monkeypatch):
    from evidence_monitor.comparison.skeptic import run_skeptic_all

    mock_provider = MagicMock()
    # Would say "label weakened" but has "none found" quote
    mock_provider.complete_json.return_value = {
        "alternative_label": "extends",
        "contradicting_quote": "none found",
        "argument": "Could be extends rather than confirms.",
        "verdict": "label weakened",  # should be overridden to "label stands"
    }
    monkeypatch.setattr("evidence_monitor.comparison.skeptic.get_provider", lambda: mock_provider)

    p1, p2 = _paper(2020), _paper(2022)
    c1 = _claim(p1)
    c2 = _claim(p2)
    with session_scope() as s:
        case = Case(anchor_claim_id=c1, new_claim_id=c2,
                    label="confirms", rationale="Matches.", confidence="high")
        s.add(case)
        s.flush()
        case_id = case.id

    run_skeptic_all()

    with session_scope() as s:
        case = s.get(Case, case_id)

    assert case.skeptic_verdict == "label stands", (
        f"'none found' quote should force 'label stands', got '{case.skeptic_verdict}'"
    )
    assert case.needs_human_attention is False


# ---------------------------------------------------------------------------
# Test 9: skeptic — real quote + "change label" sets needs_human_attention
# ---------------------------------------------------------------------------

def test_skeptic_real_quote_allows_change_label(monkeypatch):
    from evidence_monitor.comparison.skeptic import run_skeptic_all

    mock_provider = MagicMock()
    mock_provider.complete_json.return_value = {
        "alternative_label": "differs_in_context",
        "contradicting_quote": "Results varied significantly across settings.",
        "argument": "Context differs materially.",
        "verdict": "change label",
    }
    monkeypatch.setattr("evidence_monitor.comparison.skeptic.get_provider", lambda: mock_provider)

    p1, p2 = _paper(2020), _paper(2022)
    c1 = _claim(p1)
    c2 = _claim(p2)
    with session_scope() as s:
        case = Case(anchor_claim_id=c1, new_claim_id=c2,
                    label="confirms", rationale="Matches.", confidence="high")
        s.add(case)
        s.flush()
        case_id = case.id

    run_skeptic_all()

    with session_scope() as s:
        case = s.get(Case, case_id)

    assert case.skeptic_verdict == "change label"
    assert case.needs_human_attention is True
    assert case.label == "confirms"  # label NOT overwritten
    assert "Results varied" in (case.skeptic_argument or "")
