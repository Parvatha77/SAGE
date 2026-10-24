"""LLM provider abstraction: Groq (primary), Domo (stub)."""

import hashlib
import json
import logging
import os
import threading
import time
from typing import Any

import httpx

from .config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Cost table (USD per 1k tokens) for known Groq models
# ---------------------------------------------------------------------------
_GROQ_COSTS: dict[str, tuple[float, float]] = {
    "llama-3.3-70b-versatile": (0.00059, 0.00079),
    "llama-3.1-8b-instant":    (0.00005, 0.00008),
    "llama3-70b-8192":         (0.00059, 0.00079),
    "mixtral-8x7b-32768":      (0.00024, 0.00024),
    "qwen/qwen3.8-27b":        (0.00029, 0.00029),
    "openai/gpt-oss-120b":     (0.00090, 0.00090),
}

DEFAULT_GROQ_MODEL = "qwen/qwen3.8-27b"


# ---------------------------------------------------------------------------
# Cache helpers (reuse openalex cache utilities)
# ---------------------------------------------------------------------------

def _cache_key(model: str, prompt_version: str, text: str) -> str:
    blob = json.dumps({"model": model, "pv": prompt_version, "text": text},
                      sort_keys=True).encode()
    return hashlib.sha256(blob).hexdigest()


def _cache_path(key: str):
    from .sources.openalex import _cache_path as _oa_cache_path
    return _oa_cache_path(f"llm_{key}")


def _read_cache(key: str) -> Any | None:
    p = _cache_path(key)
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return None


def _write_cache(key: str, data: Any) -> None:
    _cache_path(key).write_text(json.dumps(data), encoding="utf-8")


# ---------------------------------------------------------------------------
# Rate-limit token bucket (per-provider, thread-safe)
# ---------------------------------------------------------------------------

class _RpmLimiter:
    """Simple token-bucket enforcing requests-per-minute."""

    def __init__(self, rpm: int):
        self._rpm = rpm
        self._lock = threading.Lock()
        self._tokens = rpm
        self._last_refill = time.monotonic()

    def acquire(self) -> None:
        if self._rpm <= 0:
            return
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_refill
            refill = elapsed * (self._rpm / 60.0)
            self._tokens = min(self._rpm, self._tokens + refill)
            self._last_refill = now
            if self._tokens < 1:
                wait = (1 - self._tokens) * (60.0 / self._rpm)
                logger.debug("RPM cap: sleeping %.2fs", wait)
                time.sleep(wait)
                self._tokens = 0
            else:
                self._tokens -= 1


class _RateLimitError(Exception):
    """Raised internally when a key is rate-limited so we can rotate."""


# ---------------------------------------------------------------------------
# Provider interface
# ---------------------------------------------------------------------------

class LLMProvider:
    def complete_json(
        self,
        system: str,
        user: str,
        prompt_version: str,
        model: str | None = None,
    ) -> dict:
        """Call the LLM and return a parsed JSON dict. Cached."""
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Groq provider
# ---------------------------------------------------------------------------

class GroqProvider(LLMProvider):
    BASE_URL = "https://api.groq.com/openai/v1/chat/completions"

    def __init__(self):
        self._keys = settings.all_groq_keys()
        if not self._keys:
            raise ValueError("No Groq API keys configured. Set GROQ_API_KEY in .env")
        self._key_index = 0
        self._key_lock = threading.Lock()
        # RPM cap applies per key, so effective limit scales with key count
        rpm = settings.groq_rpm_cap
        self._limiters = [_RpmLimiter(rpm) for _ in self._keys]
        logger.info("GroqProvider: %d key(s) loaded", len(self._keys))

    def _next_key(self) -> tuple[str, _RpmLimiter]:
        with self._key_lock:
            idx = self._key_index % len(self._keys)
            self._key_index += 1
        return self._keys[idx], self._limiters[idx]

    def complete_json(
        self,
        system: str,
        user: str,
        prompt_version: str,
        model: str | None = None,
    ) -> dict:
        model = model or settings.extraction_model or DEFAULT_GROQ_MODEL
        cache_key = _cache_key(model, prompt_version, system + "\n" + user)

        cached = _read_cache(cache_key)
        if cached is not None:
            logger.debug("LLM cache hit for key %s", cache_key[:12])
            return cached

        # Try each key; if all rate-limited, wait 60s and retry
        n = len(self._keys)
        for round_ in range(10):
            for _ in range(n):
                api_key, limiter = self._next_key()
                limiter.acquire()
                try:
                    result = self._call_once(model, system, user, api_key)
                    _write_cache(cache_key, result)
                    return result
                except _RateLimitError:
                    logger.warning("Key %s rate-limited, rotating", api_key[:12])
            logger.warning("All %d keys rate-limited, sleeping 60s for window reset", n)
            time.sleep(60)
        raise RuntimeError("Groq failed after exhausting all keys and retries")

    def _call_once(self, model: str, system: str, user: str, api_key: str) -> dict:
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0,
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        resp = httpx.post(self.BASE_URL, json=payload, headers=headers, timeout=60)
        if resp.status_code == 429:
            raise _RateLimitError()
        if resp.status_code >= 500:
            raise _RateLimitError()
        resp.raise_for_status()
        data = resp.json()
        self._log_usage(model, data)
        return json.loads(data["choices"][0]["message"]["content"])

    def _call_with_retry(self, model: str, system: str, user: str, api_key: str) -> dict:
        # kept for compatibility — delegates to _call_once
        return self._call_once(model, system, user, api_key)


    def _log_usage(self, model: str, data: dict) -> None:
        usage = data.get("usage", {})
        in_tok = usage.get("prompt_tokens", 0)
        out_tok = usage.get("completion_tokens", 0)
        in_cost, out_cost = _GROQ_COSTS.get(model, (0.0, 0.0))
        cost = (in_tok / 1000) * in_cost + (out_tok / 1000) * out_cost
        logger.info(
            "Groq %s | in=%d out=%d tokens | cost=$%.6f", model, in_tok, out_tok, cost
        )


# ---------------------------------------------------------------------------
# Domo provider (OpenAI-compatible endpoint)
# ---------------------------------------------------------------------------

class DomoProvider(LLMProvider):
    """Calls Domo's /ai/v1/text/generation endpoint with X-DOMO-Developer-Token auth."""

    def __init__(self):
        if not settings.domo_base_url or not settings.domo_api_key:
            raise ValueError("DOMO_BASE_URL and DOMO_API_KEY must be set in .env")
        base = settings.domo_base_url.rstrip("/")
        self.endpoint = f"{base}/ai/v1/text/generation"
        self._key = settings.domo_api_key
        self._model = settings.assessment_model
        self._limiter = _RpmLimiter(60)
        logger.info("DomoProvider: endpoint=%s model=%s", self.endpoint, self._model)

    def complete_json(
        self,
        system: str,
        user: str,
        prompt_version: str,
        model: str | None = None,
    ) -> dict:
        model = model or self._model
        cache_key = _cache_key(model, prompt_version, system + "\n" + user)
        cached = _read_cache(cache_key)
        if cached is not None:
            logger.debug("LLM cache hit (Domo) %s", cache_key[:12])
            return cached

        self._limiter.acquire()
        result = self._call(model, system, user)
        _write_cache(cache_key, result)
        return result

    def _call(self, model: str, system: str, user: str) -> dict:
        payload: dict = {"input": user, "system": system}
        if model:
            payload["model"] = model
        headers = {
            "X-DOMO-Developer-Token": self._key,
            "Content-Type": "application/json",
        }
        delay = 2.0
        for attempt in range(5):
            try:
                resp = httpx.post(self.endpoint, json=payload, headers=headers, timeout=60)
            except httpx.TimeoutException:
                if attempt == 4:
                    raise
                time.sleep(delay); delay *= 2
                continue
            if resp.status_code == 429 or resp.status_code >= 500:
                retry_after = float(resp.headers.get("Retry-After", delay))
                logger.warning("Domo HTTP %d attempt %d, sleeping %.1fs", resp.status_code, attempt + 1, retry_after)
                time.sleep(retry_after); delay = min(delay * 2, 60)
                continue
            resp.raise_for_status()
            data = resp.json()
            # Domo returns {"output": "..."} — strip markdown fences if present
            text = data.get("output", "")
            import re
            text = re.sub(r"^\s*```[a-zA-Z]*\s*\n?(.*?)\n?\s*```\s*$", r"\1", text, flags=re.DOTALL).strip()
            usage = data.get("modelProviderUsage", {})
            logger.info("Domo %s | tokens=%s", model, usage.get("totalTokens", "?"))
            return json.loads(text)
        raise RuntimeError("Domo provider failed after retries")


# ---------------------------------------------------------------------------
# Factory (singleton — preserves key rotation state across calls)
# ---------------------------------------------------------------------------

_provider: LLMProvider | None = None


def get_provider() -> LLMProvider:
    global _provider
    if _provider is None:
        name = settings.llm_provider.lower()
        if name == "groq":
            _provider = GroqProvider()
        elif name == "domo":
            _provider = DomoProvider()
        else:
            raise ValueError(f"Unknown LLM_PROVIDER: {name!r}. Choose 'groq' or 'domo'.")
    return _provider
