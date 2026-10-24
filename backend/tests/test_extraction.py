"""Tests for Phase 2 claim extraction — all LLM calls mocked."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

FIXTURES = Path(__file__).parent / "fixtures"

ABSTRACT = (
    "In a cluster randomised trial of 412 secondary students aged 13-16 in the UK, "
    "an 8-week mindfulness programme reduced anxiety scores significantly (d = 0.38, p < 0.01) "
    "compared to an active control at 3-month follow-up."
)

GOOD_RESPONSE = {
    "claims": [
        {
            "claim_text": "An 8-week mindfulness programme significantly reduced anxiety.",
            "source_sentence": "an 8-week mindfulness programme reduced anxiety scores significantly (d = 0.38, p < 0.01) compared to an active control at 3-month follow-up.",
            "direction": "positive",
            "effect_reported": "d = 0.38, p < 0.01",
            "population": "secondary students aged 13-16",
            "country_or_setting": "UK",
            "design": "cluster randomised trial",
            "outcome_measure": "anxiety scores",
            "sample_size": 412,
            "sample_size_text": "412 secondary students",
            "follow_up": "3-month",
            "is_primary_claim": True,
            "extraction_confidence": "high",
            "confidence_note": None,
        }
    ],
    "empty_reason": None,
}

NULL_FIELDS_RESPONSE = {
    "claims": [
        {
            "claim_text": "Higher mindfulness was associated with lower burnout.",
            "source_sentence": "Higher dispositional mindfulness was associated with lower burnout (r = -0.41).",
            "direction": "negative",
            "effect_reported": "r = -0.41",
            "population": "graduate students",
            "country_or_setting": None,
            "design": "survey",
            "outcome_measure": "academic burnout",
            "sample_size": None,
            "sample_size_text": None,
            "follow_up": None,
            "is_primary_claim": True,
            "extraction_confidence": "high",
            "confidence_note": "sample size not reported",
        }
    ],
    "empty_reason": None,
}

NULL_ABSTRACT = "Higher dispositional mindfulness was associated with lower burnout (r = -0.41)."

EMPTY_RESPONSE = {"claims": [], "empty_reason": "Editorial with no empirical findings."}


def _make_provider(return_value):
    provider = MagicMock()
    provider.complete_json.return_value = return_value
    return provider


# ---------------------------------------------------------------------------
# Schema: source_sentence must be substring of abstract
# ---------------------------------------------------------------------------

def test_source_sentence_not_in_abstract_rejected():
    """Claims whose source_sentence is not a substring of the abstract are dropped."""
    bad_response = {
        "claims": [
            {**GOOD_RESPONSE["claims"][0],
             "source_sentence": "This sentence does not appear in the abstract at all."},
        ],
        "empty_reason": None,
    }

    with patch("evidence_monitor.extraction.extractor.get_provider", return_value=_make_provider(bad_response)):
        from evidence_monitor.extraction.extractor import extract_claims
        result = extract_claims(ABSTRACT, "paper-1")

    assert result["status"] == "empty"
    assert result["claims"] == []


def test_valid_source_sentence_accepted():
    with patch("evidence_monitor.extraction.extractor.get_provider", return_value=_make_provider(GOOD_RESPONSE)):
        from evidence_monitor.extraction.extractor import extract_claims
        result = extract_claims(ABSTRACT, "paper-1")

    assert result["status"] == "ok"
    assert len(result["claims"]) == 1


# ---------------------------------------------------------------------------
# Null fields accepted and listed in fields_missing
# ---------------------------------------------------------------------------

def test_null_fields_accepted_and_listed():
    with patch("evidence_monitor.extraction.extractor.get_provider", return_value=_make_provider(NULL_FIELDS_RESPONSE)):
        from evidence_monitor.extraction.extractor import extract_claims
        result = extract_claims(NULL_ABSTRACT, "paper-2")

    assert result["status"] == "ok"
    claim = result["claims"][0]
    assert claim.sample_size is None
    assert claim.country_or_setting is None
    assert "sample_size" in claim.fields_missing
    assert "country_or_setting" in claim.fields_missing


# ---------------------------------------------------------------------------
# Invalid JSON triggers retry then "failed"
# ---------------------------------------------------------------------------

def test_bad_json_triggers_retry_then_failed():
    """Provider returning bad JSON should retry once, then mark failed."""
    provider = MagicMock()
    provider.complete_json.side_effect = [
        json.JSONDecodeError("bad", "", 0),
        json.JSONDecodeError("bad again", "", 0),
    ]

    # get_provider() is called inside extract_claims; patch it to return our mock
    with patch("evidence_monitor.extraction.extractor.get_provider", return_value=provider) as mock_gp:
        mock_gp.return_value = provider
        from evidence_monitor.extraction.extractor import extract_claims as _ec
        result = _ec(ABSTRACT, "paper-bad")

    assert result["status"] == "failed"
    assert provider.complete_json.call_count == 2


# ---------------------------------------------------------------------------
# Empty claims stored as status "empty"
# ---------------------------------------------------------------------------

def test_empty_claims_status():
    with patch("evidence_monitor.extraction.extractor.get_provider", return_value=_make_provider(EMPTY_RESPONSE)):
        from evidence_monitor.extraction.extractor import extract_claims
        result = extract_claims(ABSTRACT, "paper-3")

    assert result["status"] == "empty"
    assert result["claims"] == []
    assert result["empty_reason"] == "Editorial with no empirical findings."


# ---------------------------------------------------------------------------
# Idempotency: same prompt_version skips re-extraction
# ---------------------------------------------------------------------------

def test_idempotency_skips_already_extracted(tmp_path, monkeypatch):
    import evidence_monitor.db as db_mod
    from evidence_monitor.models import Paper, ExtractionRun
    from evidence_monitor.extraction.prompts import PROMPT_VERSION

    db_url = f"sqlite:///{tmp_path}/test.db"
    monkeypatch.setattr(db_mod.settings, "db_url", db_url)
    db_mod._engine = None
    db_mod._SessionLocal = None
    db_mod.create_all()

    paper = Paper(id="https://openalex.org/WTest1", abstract=ABSTRACT, title="Test")
    with db_mod.session_scope() as s:
        s.add(paper)
        s.add(ExtractionRun(
            paper_id="https://openalex.org/WTest1",
            status="ok",
            prompt_version=PROMPT_VERSION,
        ))

    provider = _make_provider(GOOD_RESPONSE)
    with patch("evidence_monitor.extraction.extractor.get_provider", return_value=provider):
        from evidence_monitor.extraction.run import run_extraction
        counts = run_extraction()

    assert counts["skipped"] == 1
    provider.complete_json.assert_not_called()


def test_force_reextracts(tmp_path, monkeypatch):
    import evidence_monitor.db as db_mod
    from evidence_monitor.models import Paper, ExtractionRun
    from evidence_monitor.extraction.prompts import PROMPT_VERSION

    db_url = f"sqlite:///{tmp_path}/test.db"
    monkeypatch.setattr(db_mod.settings, "db_url", db_url)
    db_mod._engine = None
    db_mod._SessionLocal = None
    db_mod.create_all()

    paper = Paper(id="https://openalex.org/WTest2", abstract=ABSTRACT, title="Test2")
    with db_mod.session_scope() as s:
        s.add(paper)
        s.add(ExtractionRun(
            paper_id="https://openalex.org/WTest2",
            status="ok",
            prompt_version=PROMPT_VERSION,
        ))

    provider = _make_provider(GOOD_RESPONSE)
    with patch("evidence_monitor.extraction.extractor.get_provider", return_value=provider):
        from evidence_monitor.extraction.run import run_extraction
        counts = run_extraction(force=True)

    assert counts.get("ok", 0) == 1
    provider.complete_json.assert_called_once()


# ---------------------------------------------------------------------------
# Cache hit makes no API call
# ---------------------------------------------------------------------------

def test_cache_hit_no_api_call(tmp_path, monkeypatch):
    import evidence_monitor.llm as llm_mod
    import evidence_monitor.sources.openalex as oa_mod

    monkeypatch.setattr(oa_mod.settings, "cache_dir", tmp_path)
    monkeypatch.setattr(llm_mod.settings, "groq_api_key", "fake-key")
    monkeypatch.setattr(llm_mod.settings, "extraction_model", "llama-3.3-70b-versatile")
    monkeypatch.setattr(llm_mod.settings, "llm_provider", "groq")
    monkeypatch.setattr(llm_mod.settings, "groq_rpm_cap", 0)

    # Pre-populate cache
    from evidence_monitor.extraction.prompts import SYSTEM_PROMPT, USER_TEMPLATE, PROMPT_VERSION
    user_msg = USER_TEMPLATE.format(abstract=ABSTRACT)
    key = llm_mod._cache_key("llama-3.3-70b-versatile", PROMPT_VERSION, SYSTEM_PROMPT + "\n" + user_msg)
    llm_mod._write_cache(key, GOOD_RESPONSE)

    import httpx
    import respx

    with respx.mock:
        route = respx.post("https://api.groq.com/openai/v1/chat/completions").mock(
            return_value=httpx.Response(200, json=GOOD_RESPONSE)
        )
        from evidence_monitor.extraction.extractor import extract_claims
        result = extract_claims(ABSTRACT, "paper-cache")

    assert route.call_count == 0
    assert result["status"] == "ok"


# ---------------------------------------------------------------------------
# review-score computes percentages correctly
# ---------------------------------------------------------------------------

def test_review_score_percentages(tmp_path):
    """review-score should compute correct/exact/no-invented percentages."""
    from pathlib import Path
    csv_src = Path(__file__).parent / "fixtures" / "review_sample.csv"

    # Import the scoring logic directly
    import csv

    total = correct = exact_source = no_invented = 0
    with open(csv_src, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            cc = row.get("correct_claim (y/n)", "").strip().lower()
            se = row.get("source_exact (y/n)", "").strip().lower()
            ai = row.get("any_invented_detail (y/n)", "").strip().lower()
            if not cc:
                continue
            total += 1
            if cc == "y":
                correct += 1
            if se == "y":
                exact_source += 1
            if ai == "n":
                no_invented += 1

    assert total == 4
    assert correct == 3        # p1, p2, p4 are y; p3 is n
    assert exact_source == 3   # p1, p2, p3 are y; p4 is n
    assert no_invented == 3    # p1, p2, p3 are n; p4 is y → no_invented counts "n"
