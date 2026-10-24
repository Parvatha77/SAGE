"""Tests for the Crossref client."""

import json
from pathlib import Path

import httpx
import pytest
import respx

FIXTURES = Path(__file__).parent / "fixtures"
DOI = "10.1016/j.paid.2017.07.011"
CROSSREF_URL = f"https://api.crossref.org/works/{DOI}"


@respx.mock
def test_retraction_notice_parsed(tmp_path, monkeypatch):
    """A Crossref retraction record produces one IntegrityNotice of kind 'retraction'."""
    import evidence_monitor.sources.crossref as cr_mod
    import evidence_monitor.sources.openalex as oa_mod

    monkeypatch.setattr(oa_mod.settings, "cache_dir", tmp_path)
    monkeypatch.setattr(cr_mod.settings, "cache_dir", tmp_path)

    payload = json.loads((FIXTURES / "crossref_retraction.json").read_text())
    respx.get(CROSSREF_URL).mock(return_value=httpx.Response(200, json=payload))

    notices = cr_mod.check_updates(DOI)
    assert len(notices) == 1
    assert notices[0]["kind"] == "retraction"
    assert notices[0]["source"] == "crossref"
    assert notices[0]["notice_doi"] == "10.1016/j.paid.2022.01.001"
    assert notices[0]["notice_date"] == "2022-01-15"


@respx.mock
def test_clean_paper_no_notices(tmp_path, monkeypatch):
    import evidence_monitor.sources.crossref as cr_mod
    import evidence_monitor.sources.openalex as oa_mod

    monkeypatch.setattr(oa_mod.settings, "cache_dir", tmp_path)
    monkeypatch.setattr(cr_mod.settings, "cache_dir", tmp_path)

    clean_doi = "10.9999/clean.2020.001"
    payload = json.loads((FIXTURES / "crossref_clean.json").read_text())
    respx.get(f"https://api.crossref.org/works/{clean_doi}").mock(
        return_value=httpx.Response(200, json=payload)
    )

    notices = cr_mod.check_updates(clean_doi)
    assert notices == []


@respx.mock
def test_crossref_cache(tmp_path, monkeypatch):
    """Second call to check_updates must not hit the network."""
    import evidence_monitor.sources.crossref as cr_mod
    import evidence_monitor.sources.openalex as oa_mod

    monkeypatch.setattr(oa_mod.settings, "cache_dir", tmp_path)
    monkeypatch.setattr(cr_mod.settings, "cache_dir", tmp_path)

    payload = json.loads((FIXTURES / "crossref_retraction.json").read_text())
    route = respx.get(CROSSREF_URL).mock(return_value=httpx.Response(200, json=payload))

    cr_mod.check_updates(DOI)
    cr_mod.check_updates(DOI)

    assert route.call_count == 1


@respx.mock
def test_crossref_retry_429(tmp_path, monkeypatch):
    import evidence_monitor.sources.crossref as cr_mod
    import evidence_monitor.sources.openalex as oa_mod

    monkeypatch.setattr(oa_mod.settings, "cache_dir", tmp_path)
    monkeypatch.setattr(cr_mod.settings, "cache_dir", tmp_path)
    monkeypatch.setattr(cr_mod.time, "sleep", lambda _: None)

    payload = json.loads((FIXTURES / "crossref_retraction.json").read_text())
    route = respx.get(CROSSREF_URL).mock(
        side_effect=[
            httpx.Response(429, json={}, headers={"Retry-After": "0"}),
            httpx.Response(200, json=payload),
        ]
    )

    notices = cr_mod.check_updates(DOI, refresh=True)
    assert len(notices) == 1
    assert route.call_count == 2
