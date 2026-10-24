"""Crossref REST API client — retraction and correction notices."""

import logging
import time
from typing import Any

import httpx

from ..config import settings
from .openalex import _cache_key, _read_cache, _write_cache

logger = logging.getLogger(__name__)

BASE_URL = "https://api.crossref.org"

# Crossref relation types that represent integrity updates
_NOTICE_TYPES = {
    "is-retracted-by": "retraction",
    "is-corrected-by": "correction",
    "is-expression-of-concern-for": "concern",
    "is-withdrawn-by": "withdrawal",
    # also handle the reverse direction
    "retracts": "retraction",
    "corrects": "correction",
    "is-expression-of-concern": "concern",
}


def _get(url: str, params: dict, refresh: bool = False) -> Any:
    """GET with disk cache and retry logic."""
    key = _cache_key(url, params)
    if not refresh:
        cached = _read_cache(key)
        if cached is not None:
            logger.debug("Crossref cache hit: %s", key)
            return cached

    headers = {}
    if settings.crossref_mailto:
        headers["User-Agent"] = f"EvidenceMonitor/0.1 (mailto:{settings.crossref_mailto})"

    delay = 1.0
    for attempt in range(5):
        try:
            resp = httpx.get(url, params=params, headers=headers, timeout=30)
        except httpx.TimeoutException:
            if attempt == 4:
                raise
            time.sleep(delay)
            delay *= 2
            continue

        if resp.status_code == 429 or resp.status_code >= 500:
            retry_after = float(resp.headers.get("Retry-After", delay))
            logger.warning(
                "Crossref HTTP %d attempt %d, sleeping %.1fs",
                resp.status_code, attempt + 1, retry_after,
            )
            time.sleep(retry_after)
            delay = min(delay * 2, 60)
            continue

        if resp.status_code == 404:
            _write_cache(key, None)
            return None

        resp.raise_for_status()
        data = resp.json()
        _write_cache(key, data)
        return data

    raise RuntimeError(f"Crossref failed after retries: {url}")


def check_updates(doi: str, refresh: bool = False) -> list[dict]:
    """
    Return integrity notices for *doi*.

    Each dict has keys: kind, notice_doi, notice_date, source="crossref".
    """
    clean_doi = doi.lstrip("https://doi.org/").lstrip("http://doi.org/")
    url = f"{BASE_URL}/works/{clean_doi}"
    data = _get(url, {}, refresh=refresh)
    if not data:
        return []

    message = data.get("message", {})
    notices: list[dict] = []

    # Check top-level is-retracted / update-to fields (not standard but some publishers use them)
    updates = message.get("update-to", []) or []
    for upd in updates:
        upd_type = upd.get("type", "").lower()
        kind = None
        if "retract" in upd_type:
            kind = "retraction"
        elif "correct" in upd_type:
            kind = "correction"
        elif "concern" in upd_type:
            kind = "concern"
        elif "withdraw" in upd_type:
            kind = "withdrawal"
        if kind:
            notices.append({
                "kind": kind,
                "notice_doi": upd.get("DOI"),
                "notice_date": _extract_date(upd.get("updated")),
                "source": "crossref",
            })

    # Check relation block
    relations = message.get("relation", {}) or {}
    for rel_type, rel_list in relations.items():
        kind = _NOTICE_TYPES.get(rel_type)
        if not kind:
            continue
        if isinstance(rel_list, list):
            for item in rel_list:
                notice_doi = item.get("id") if isinstance(item, dict) else None
                notices.append({
                    "kind": kind,
                    "notice_doi": notice_doi,
                    "notice_date": None,
                    "source": "crossref",
                })

    return notices


def _extract_date(date_obj: Any) -> str | None:
    """Extract ISO date string from a Crossref date object."""
    if not date_obj:
        return None
    if isinstance(date_obj, str):
        return date_obj
    parts = date_obj.get("date-parts", [[]])[0]
    if parts:
        return "-".join(str(p).zfill(2) for p in parts)
    return date_obj.get("date-time", {})[:10] if isinstance(date_obj.get("date-time"), str) else None
