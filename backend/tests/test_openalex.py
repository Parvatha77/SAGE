"""Tests for the OpenAlex client."""

import json
import os
from pathlib import Path

import pytest
import respx
import httpx

FIXTURES = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Abstract rebuild
# ---------------------------------------------------------------------------

def test_rebuild_abstract_basic():
    from evidence_monitor.sources.openalex import rebuild_abstract

    index = {"hello": [0], "world": [1]}
    assert rebuild_abstract(index) == "hello world"


def test_rebuild_abstract_repeated_words():
    from evidence_monitor.sources.openalex import rebuild_abstract

    index = {"to": [5, 8], "be": [6], "or": [7], "not": [9]}
    result = rebuild_abstract(index)
    # split(" ") preserves empty slots, so positional indexing works
    words = result.split(" ")
    assert words[5] == "to"
    assert words[8] == "to"
    assert words[6] == "be"


def test_rebuild_abstract_gaps():
    from evidence_monitor.sources.openalex import rebuild_abstract

    # positions 0 and 2 filled, position 1 is empty string
    index = {"hello": [0], "world": [2]}
    result = rebuild_abstract(index)
    parts = result.split(" ")
    assert parts[0] == "hello"
    assert parts[1] == ""
    assert parts[2] == "world"


def test_rebuild_abstract_none():
    from evidence_monitor.sources.openalex import rebuild_abstract

    assert rebuild_abstract(None) is None
    assert rebuild_abstract({}) is None


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

@respx.mock
def test_cache_second_call_no_network(tmp_path, monkeypatch):
    """Second call for same params must not hit the network."""
    from evidence_monitor import sources
    import evidence_monitor.sources.openalex as oa_mod

    monkeypatch.setattr(oa_mod.settings, "cache_dir", tmp_path)
    monkeypatch.setattr(oa_mod.settings, "openalex_api_key", "")

    payload = json.loads((FIXTURES / "openalex_search.json").read_text())

    route = respx.get("https://api.openalex.org/works").mock(
        return_value=httpx.Response(200, json=payload)
    )

    params = {"search": "mindfulness", "filter": "type:article", "per-page": 25, "cursor": "*"}
    oa_mod._get("https://api.openalex.org/works", params)
    oa_mod._get("https://api.openalex.org/works", params)

    assert route.call_count == 1  # second call used cache


@respx.mock
def test_api_key_not_in_cache_filename(tmp_path, monkeypatch):
    """Cache file name must not contain the API key."""
    import evidence_monitor.sources.openalex as oa_mod

    secret = "SUPERSECRET123"
    monkeypatch.setattr(oa_mod.settings, "cache_dir", tmp_path)
    monkeypatch.setattr(oa_mod.settings, "openalex_api_key", secret)

    payload = json.loads((FIXTURES / "openalex_search.json").read_text())
    respx.get("https://api.openalex.org/works").mock(
        return_value=httpx.Response(200, json=payload)
    )

    oa_mod._get("https://api.openalex.org/works", {"search": "test"})

    for f in tmp_path.rglob("*"):
        assert secret not in f.name, f"API key found in filename: {f.name}"


# ---------------------------------------------------------------------------
# Retry on 429
# ---------------------------------------------------------------------------

@respx.mock
def test_retry_on_429(tmp_path, monkeypatch):
    """Client should retry after a 429 and eventually succeed."""
    import evidence_monitor.sources.openalex as oa_mod

    monkeypatch.setattr(oa_mod.settings, "cache_dir", tmp_path)
    monkeypatch.setattr(oa_mod.settings, "openalex_api_key", "")
    monkeypatch.setattr(oa_mod.time, "sleep", lambda _: None)  # no real sleeping

    payload = json.loads((FIXTURES / "openalex_search.json").read_text())

    route = respx.get("https://api.openalex.org/works").mock(
        side_effect=[
            httpx.Response(429, json={"error": "rate limited"}, headers={"Retry-After": "0"}),
            httpx.Response(200, json=payload),
        ]
    )

    result = oa_mod._get("https://api.openalex.org/works", {"search": "test"}, refresh=True)
    assert result["results"][0]["title"] == "Mindfulness and well-being in students"
    assert route.call_count == 2


# ---------------------------------------------------------------------------
# search_works parsing
# ---------------------------------------------------------------------------

@respx.mock
def test_search_works_returns_parsed(tmp_path, monkeypatch):
    import evidence_monitor.sources.openalex as oa_mod

    monkeypatch.setattr(oa_mod.settings, "cache_dir", tmp_path)
    monkeypatch.setattr(oa_mod.settings, "openalex_api_key", "")

    payload = json.loads((FIXTURES / "openalex_search.json").read_text())
    respx.get("https://api.openalex.org/works").mock(
        return_value=httpx.Response(200, json=payload)
    )

    works = list(oa_mod.search_works("mindfulness", max_results=10))
    assert len(works) == 1
    w = works[0]
    assert w["id"] == "https://openalex.org/W2741809807"
    assert "Mindfulness" in w["abstract"]
    assert w["authors"] == ["Alice Researcher", "Bob Scholar"]
    assert w["is_retracted"] is False
