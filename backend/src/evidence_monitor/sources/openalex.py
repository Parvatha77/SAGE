"""OpenAlex API client with disk caching and retry logic."""

import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Any, Iterator

import httpx

from ..config import settings

logger = logging.getLogger(__name__)

BASE_URL = "https://api.openalex.org"

WORK_FIELDS = (
    "id,doi,title,abstract_inverted_index,publication_date,publication_year,"
    "primary_location,authorships,referenced_works,cited_by_count,"
    "type,is_retracted,language"
)


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------

def _cache_key(url: str, params: dict) -> str:
    """Hash of URL + params, with api_key removed so it never appears in filenames."""
    safe = {k: v for k, v in params.items() if k != "api_key"}
    blob = json.dumps({"url": url, "params": safe}, sort_keys=True).encode()
    return hashlib.sha256(blob).hexdigest()


def _cache_path(key: str) -> Path:
    path = settings.cache_dir / f"{key}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _read_cache(key: str) -> Any | None:
    p = _cache_path(key)
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return None


def _write_cache(key: str, data: Any) -> None:
    _cache_path(key).write_text(json.dumps(data), encoding="utf-8")


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _get(url: str, params: dict, refresh: bool = False) -> Any:
    """GET with caching and exponential-backoff retry on 429/5xx."""
    key = _cache_key(url, params)
    if not refresh:
        cached = _read_cache(key)
        if cached is not None:
            logger.debug("Cache hit: %s", key)
            return cached

    full_params = {**params}
    if settings.openalex_api_key:
        full_params["api_key"] = settings.openalex_api_key

    delay = 1.0
    for attempt in range(5):
        try:
            resp = httpx.get(url, params=full_params, timeout=30)
        except httpx.TimeoutException as exc:
            if attempt == 4:
                raise
            logger.warning("Timeout on attempt %d, retrying in %.1fs", attempt + 1, delay)
            time.sleep(delay)
            delay *= 2
            continue

        if resp.status_code == 429 or resp.status_code >= 500:
            retry_after = float(resp.headers.get("Retry-After", delay))
            logger.warning(
                "HTTP %d on attempt %d, sleeping %.1fs", resp.status_code, attempt + 1, retry_after
            )
            time.sleep(retry_after)
            delay = min(delay * 2, 60)
            continue

        resp.raise_for_status()
        data = resp.json()
        _write_cache(key, data)
        return data

    raise RuntimeError(f"Failed after retries: {url}")


# ---------------------------------------------------------------------------
# Abstract reconstruction
# ---------------------------------------------------------------------------

def rebuild_abstract(inverted_index: dict[str, list[int]] | None) -> str | None:
    """Reconstruct abstract text from OpenAlex abstract_inverted_index."""
    if not inverted_index:
        return None
    max_pos = max(pos for positions in inverted_index.values() for pos in positions)
    words: list[str] = [""] * (max_pos + 1)
    for word, positions in inverted_index.items():
        for pos in positions:
            words[pos] = word
    return " ".join(words)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _parse_work(raw: dict) -> dict:
    """Extract and normalise the fields we care about."""
    loc = raw.get("primary_location") or {}
    source = loc.get("source") or {}
    authors = [
        a.get("author", {}).get("display_name", "")
        for a in (raw.get("authorships") or [])
    ]
    return {
        "id": raw["id"],
        "doi": raw.get("doi"),
        "title": raw.get("title"),
        "abstract": rebuild_abstract(raw.get("abstract_inverted_index")),
        "publication_date": raw.get("publication_date"),
        "publication_year": raw.get("publication_year"),
        "journal": source.get("display_name"),
        "publisher": raw.get("publisher") or source.get("host_organization_name"),
        "authors": authors,
        "referenced_works": raw.get("referenced_works") or [],
        "cited_by_count": raw.get("cited_by_count"),
        "type": raw.get("type"),
        "is_retracted": bool(raw.get("is_retracted")),
        "language": raw.get("language"),
    }


def search_works(
    query: str,
    from_year: int | None = None,
    to_year: int | None = None,
    max_results: int = 100,
    refresh: bool = False,
) -> Iterator[dict]:
    """Yield parsed work dicts matching *query* via cursor pagination."""
    filters = ["type:article"]
    if from_year and to_year:
        filters.append(f"publication_year:{from_year}-{to_year}")
    elif from_year:
        filters.append(f"publication_year:>{from_year - 1}")
    elif to_year:
        filters.append(f"publication_year:<{to_year + 1}")

    params: dict[str, Any] = {
        "search": query,
        "filter": ",".join(filters),
        "select": WORK_FIELDS,
        "per-page": min(max_results, 200),
        "cursor": "*",
    }

    yielded = 0
    while yielded < max_results:
        data = _get(f"{BASE_URL}/works", params, refresh=refresh)
        results = data.get("results", [])
        if not results:
            break
        for raw in results:
            if yielded >= max_results:
                return
            yield _parse_work(raw)
            yielded += 1
        cursor = data.get("meta", {}).get("next_cursor")
        if not cursor:
            break
        params = {**params, "cursor": cursor}


def get_work(openalex_id_or_doi: str, refresh: bool = False) -> dict | None:
    """Fetch a single work by OpenAlex id or DOI."""
    identifier = openalex_id_or_doi
    if identifier.startswith("10."):
        identifier = f"doi:{identifier}"
    url = f"{BASE_URL}/works/{identifier}"
    try:
        raw = _get(url, {"select": WORK_FIELDS}, refresh=refresh)
        return _parse_work(raw)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            return None
        raise


def fetch_retracted_works(
    query: str,
    max_results: int = 5,
    refresh: bool = False,
) -> Iterator[dict]:
    """Yield works with is_retracted:true that match *query*."""
    params: dict[str, Any] = {
        "search": query,
        "filter": "is_retracted:true",
        "select": WORK_FIELDS,
        "per-page": min(max_results, 200),
        "cursor": "*",
    }

    yielded = 0
    while yielded < max_results:
        data = _get(f"{BASE_URL}/works", params, refresh=refresh)
        results = data.get("results", [])
        if not results:
            break
        for raw in results:
            if yielded >= max_results:
                return
            yield _parse_work(raw)
            yielded += 1
        cursor = data.get("meta", {}).get("next_cursor")
        if not cursor:
            break
        params = {**params, "cursor": cursor}


def get_citing_works(
    openalex_id: str,
    since_date: str | None = None,
    max_results: int = 500,
    refresh: bool = False,
) -> Iterator[dict]:
    """Yield works that cite *openalex_id*, optionally filtered by date."""
    filters = [f"cites:{openalex_id}"]
    if since_date:
        filters.append(f"from_publication_date:{since_date}")

    params: dict[str, Any] = {
        "filter": ",".join(filters),
        "select": WORK_FIELDS,
        "per-page": min(max_results, 200),
        "cursor": "*",
    }

    yielded = 0
    while yielded < max_results:
        data = _get(f"{BASE_URL}/works", params, refresh=refresh)
        results = data.get("results", [])
        if not results:
            break
        for raw in results:
            if yielded >= max_results:
                return
            yield _parse_work(raw)
            yielded += 1
        cursor = data.get("meta", {}).get("next_cursor")
        if not cursor:
            break
        params = {**params, "cursor": cursor}
