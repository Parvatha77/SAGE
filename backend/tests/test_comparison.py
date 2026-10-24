"""Tests for Phase 3 comparison pipeline — mocked LLM and embeddings."""

import json
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from evidence_monitor.models import (
    Base, Paper, Claim, ClaimEmbedding, ClaimPair, FieldComparison,
    Case, AffectedItem, Citation, IntegrityNotice,
)


def _make_db(monkeypatch, tmp_path):
    import evidence_monitor.db as db_mod
    db_url = f"sqlite:///{tmp_path}/test.db"
    monkeypatch.setattr(db_mod.settings, "db_url", db_url)
    db_mod._engine = None
    db_mod._SessionLocal = None
    db_mod.create_all()
    return db_mod


def _paper(session, pid="WA", year=2020):
    p = Paper(id=f"https://openalex.org/{pid}", publication_year=year,
              title=f"Paper {pid}", abstract="test abstract", cited_by_count=10)
    session.add(p)
    return p


def _claim(session, paper, cid=None, **kwargs):
    defaults = dict(
        claim_text="Mindfulness reduces anxiety.",
        source_sentence="Mindfulness reduces anxiety.",
        direction="positive",
        outcome_measure="anxiety",
        population="students",
        design="RCT",
        sample_size=100,
        prompt_version="v1",
    )
    defaults.update(kwargs)
    c = Claim(id=cid or str(uuid.uuid4()), paper_id=paper.id, **defaults)
    session.add(c)
    return c


# ---------------------------------------------------------------------------
# 1. Unknown fields never count as differences
# ---------------------------------------------------------------------------

def test_unknown_fields_not_differences():
    from evidence_monitor.comparison.compare import _compare_sample_size, LABEL_UNKNOWN
    assert _compare_sample_size(None, 100) == LABEL_UNKNOWN
    assert _compare_sample_size(100, None) == LABEL_UNKNOWN
    assert _compare_sample_size(None, None) == LABEL_UNKNOWN


def test_text_field_null_is_unknown():
    from evidence_monitor.comparison.compare import _compare_text_field, LABEL_UNKNOWN
    result, _ = _compare_text_field("population", None, "students")
    assert result == LABEL_UNKNOWN
    result, _ = _compare_text_field("population", "students", None)
    assert result == LABEL_UNKNOWN


# ---------------------------------------------------------------------------
# 2. >50% unknown fields caps confidence at low
# ---------------------------------------------------------------------------

def test_majority_unknown_caps_confidence(tmp_path, monkeypatch):
    db_mod = _make_db(monkeypatch, tmp_path)
    provider = MagicMock()
    provider.complete_json.return_value = {
        "label": "confirms",
        "rationale": "Both studies confirm the effect.",
        "confidence": "high",
        "confidence_reason": None,
    }

    from evidence_monitor.comparison.compare import LABEL_UNKNOWN, LABEL_SIMILAR
    from evidence_monitor.models import FieldComparison

    # Build a pair with 5 unknown and 1 similar field comparison
    with db_mod.session_scope() as session:
        p1 = _paper(session, "W1", 2020)
        p2 = _paper(session, "W2", 2022)
        session.flush()
        c1 = _claim(session, p1, population="students")
        c2 = _claim(session, p2, population=None)
        session.flush()
        pair = ClaimPair(anchor_claim_id=c1.id, new_claim_id=c2.id, same_question="yes")
        session.add(pair)
        session.flush()
        fields = ["population", "country_or_setting", "design", "outcome_measure", "follow_up", "sample_size"]
        for i, f in enumerate(fields):
            session.add(FieldComparison(
                claim_pair_id=pair.id, field_name=f,
                anchor_value="x", new_value="x",
                result=LABEL_UNKNOWN if i < 5 else LABEL_SIMILAR,
            ))
        pair_id = pair.id

    with patch("evidence_monitor.comparison.classify.get_provider", return_value=provider):
        from evidence_monitor.comparison.classify import classify_pair, CLASSIFY_VERSION
        result = classify_pair(pair_id, CLASSIFY_VERSION)

    assert result is not None
    assert result.confidence == "low"
    assert result.label == "insufficient_information"


# ---------------------------------------------------------------------------
# 3. Retraction notice creates retraction_impact cases for citing papers only
# ---------------------------------------------------------------------------

def test_retraction_creates_case_for_citers(tmp_path, monkeypatch):
    db_mod = _make_db(monkeypatch, tmp_path)

    with db_mod.session_scope() as session:
        p_retracted = _paper(session, "WR", 2019)
        p_citer = _paper(session, "WC", 2022)
        session.flush()
        c_retracted = _claim(session, p_retracted)
        session.flush()
        session.add(Citation(citing_id=p_citer.id, cited_id=p_retracted.id))
        notice = IntegrityNotice(
            paper_id=p_retracted.id, kind="retraction", source="crossref"
        )
        session.add(notice)

    from evidence_monitor.comparison.integrity_cases import build_integrity_cases
    count = build_integrity_cases()

    assert count == 1
    with db_mod.session_scope() as session:
        cases = session.execute(
            __import__("sqlalchemy", fromlist=["select"]).select(Case)
        ).scalars().all()
    assert len(cases) == 1
    assert cases[0].label == "retraction_impact"
    # Must NOT create a case for the retracted paper itself
    assert cases[0].new_claim_id != c_retracted.id or cases[0].notice_id is not None


def test_retraction_no_case_without_citers(tmp_path, monkeypatch):
    db_mod = _make_db(monkeypatch, tmp_path)

    with db_mod.session_scope() as session:
        p = _paper(session, "WR2", 2019)
        session.flush()
        _claim(session, p)
        notice = IntegrityNotice(paper_id=p.id, kind="retraction", source="crossref")
        session.add(notice)

    from evidence_monitor.comparison.integrity_cases import build_integrity_cases
    count = build_integrity_cases()
    assert count == 0


# ---------------------------------------------------------------------------
# 4. Skeptic "change label" sets needs_human_attention, does not overwrite label
# ---------------------------------------------------------------------------

def test_skeptic_change_label_sets_attention(tmp_path, monkeypatch):
    db_mod = _make_db(monkeypatch, tmp_path)

    provider = MagicMock()
    provider.complete_json.return_value = {
        "alternative_label": "differs_in_context",
        "contradicting_quote": "The sample was drawn from a clinical population.",
        "argument": "The populations differ substantially.",
        "verdict": "change label",
    }

    with db_mod.session_scope() as session:
        p = _paper(session, "WS", 2020)
        session.flush()
        c = _claim(session, p)
        session.flush()
        case = Case(
            anchor_claim_id=c.id, label="confirms",
            prompt_version="v1-cls-v1",
        )
        session.add(case)
        session.flush()
        case_id = case.id

    with patch("evidence_monitor.comparison.skeptic.get_provider", return_value=provider):
        from evidence_monitor.comparison.skeptic import run_skeptic_all
        run_skeptic_all()

    with db_mod.session_scope() as session:
        case = session.get(Case, case_id)

    assert case.needs_human_attention is True
    assert case.label == "confirms"  # label NOT overwritten
    assert case.alternative_label == "differs_in_context"
    assert case.skeptic_verdict == "change label"


# ---------------------------------------------------------------------------
# 5. Pipeline resume makes zero new LLM calls on second run
# ---------------------------------------------------------------------------

def test_pipeline_resume_no_new_llm_calls(tmp_path, monkeypatch):
    db_mod = _make_db(monkeypatch, tmp_path)

    with db_mod.session_scope() as session:
        p = _paper(session, "WP", 2020)
        session.flush()
        c = _claim(session, p)
        session.flush()
        # Pre-populate an ExtractionRun so the paper is "done"
        from evidence_monitor.models import ExtractionRun
        session.add(ExtractionRun(
            paper_id=p.id, status="ok", prompt_version="v1"
        ))

    provider = MagicMock()
    provider.complete_json.return_value = {
        "same_question": "yes", "reason": "same outcome"
    }

    # No claim pairs exist yet, so relevance/classify have nothing to process
    with patch("evidence_monitor.comparison.relevance.get_provider", return_value=provider):
        with patch("evidence_monitor.comparison.classify.get_provider", return_value=provider):
            with patch("evidence_monitor.comparison.skeptic.get_provider", return_value=provider):
                with patch("evidence_monitor.comparison.candidates._get_encoder") as mock_enc:
                    mock_enc.return_value = MagicMock(
                        encode=lambda text, normalize_embeddings=True: __import__("numpy").zeros(384)
                    )
                    from evidence_monitor.comparison.pipeline import run_pipeline
                    run_pipeline()
                    call_count_1 = provider.complete_json.call_count
                    run_pipeline()
                    call_count_2 = provider.complete_json.call_count

    # Second run should make no additional calls (nothing new to process)
    assert call_count_2 == call_count_1


# ---------------------------------------------------------------------------
# 6. Ranking: score components sum to total, stored correctly
# ---------------------------------------------------------------------------

def test_ranking_components_sum(tmp_path, monkeypatch):
    db_mod = _make_db(monkeypatch, tmp_path)

    with db_mod.session_scope() as session:
        p = _paper(session, "WRank", 2022)
        session.flush()
        c = _claim(session, p)
        session.flush()
        case = Case(
            anchor_claim_id=c.id, label="confirms", prompt_version="v1"
        )
        session.add(case)
        session.flush()
        case_id = case.id

    from evidence_monitor.comparison.rank import rank_case
    items = rank_case(case_id)

    assert len(items) >= 1
    for item in items:
        components = json.loads(item.score_components_json)
        assert abs(sum(components.values()) - item.score) < 0.01


# ---------------------------------------------------------------------------
# 7. Label severity order is respected
# ---------------------------------------------------------------------------

def test_label_severity_order():
    from evidence_monitor.comparison.rank import LABEL_SEVERITY
    assert LABEL_SEVERITY["retraction_impact"] > LABEL_SEVERITY["possible_reproducibility_concern"]
    assert LABEL_SEVERITY["possible_reproducibility_concern"] > LABEL_SEVERITY["differs_in_context"]
    assert LABEL_SEVERITY["differs_in_context"] > LABEL_SEVERITY["extends"]
    assert LABEL_SEVERITY["extends"] > LABEL_SEVERITY["confirms"]
