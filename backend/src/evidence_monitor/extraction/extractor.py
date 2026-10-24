"""Extract empirical claims from a paper's abstract using an LLM."""

import json
import logging

from pydantic import ValidationError

from ..llm import get_provider, _GROQ_COSTS, DEFAULT_GROQ_MODEL
from ..config import settings
from .schema import ClaimData, ExtractionResult
from .prompts import SYSTEM_PROMPT, USER_TEMPLATE, PROMPT_VERSION

logger = logging.getLogger(__name__)

# Cost table lookup for token cost estimate
def _estimate_cost(model: str, in_tok: int, out_tok: int) -> float:
    in_c, out_c = _GROQ_COSTS.get(model, (0.0, 0.0))
    return (in_tok / 1000) * in_c + (out_tok / 1000) * out_c


def extract_claims(paper_abstract: str, paper_id: str) -> dict:
    """
    Run claim extraction for one abstract.

    Returns a dict with keys:
      status: "ok" | "empty" | "failed"
      claims: list[ClaimData]
      empty_reason: str | None
      error: str | None
      input_tokens: int
      output_tokens: int
      cost_estimate: float
      prompt_version: str
      model: str
    """
    model = settings.extraction_model or DEFAULT_GROQ_MODEL
    provider = get_provider()
    user_msg = USER_TEMPLATE.format(abstract=paper_abstract)

    def _attempt(extra_prefix: str = "") -> dict:
        msg = extra_prefix + user_msg if extra_prefix else user_msg
        return provider.complete_json(
            system=SYSTEM_PROMPT,
            user=msg,
            prompt_version=PROMPT_VERSION,
            model=model,
        )

    # First attempt
    try:
        raw = _attempt()
        result, rejected = _validate_and_filter(raw, paper_abstract)
        if rejected:
            logger.info(
                "Paper %s: %d claim(s) rejected (source_sentence not in abstract)",
                paper_id, rejected,
            )
    except (ValidationError, KeyError, ValueError) as exc:
        logger.warning("Paper %s: first parse failed (%s), retrying", paper_id, exc)
        # Retry with validation error context
        try:
            raw = _attempt(
                extra_prefix=f"Your previous response failed validation: {exc}\n"
                             "Fix the issues and try again.\n\n"
            )
            result, rejected = _validate_and_filter(raw, paper_abstract)
        except Exception as exc2:
            logger.error("Paper %s: retry also failed: %s", paper_id, exc2)
            return _failed(model, str(exc2))
    except Exception as exc:
        logger.error("Paper %s: LLM call failed: %s", paper_id, exc)
        return _failed(model, str(exc))

    status = "empty" if not result.claims else "ok"
    return {
        "status": status,
        "claims": result.claims,
        "empty_reason": result.empty_reason,
        "error": None,
        "input_tokens": 0,   # tokens not returned from cached path; provider logs them
        "output_tokens": 0,
        "cost_estimate": 0.0,
        "prompt_version": PROMPT_VERSION,
        "model": model,
    }


def _validate_and_filter(
    raw: dict, abstract: str
) -> tuple[ExtractionResult, int]:
    """Validate raw dict against schema, reject claims with bad source_sentence."""
    result = ExtractionResult.model_validate(raw)
    rejected = 0
    valid_claims = []
    for claim in result.claims:
        if claim.source_sentence not in abstract:
            logger.warning(
                "Rejecting claim — source_sentence not found in abstract: %r",
                claim.source_sentence[:80],
            )
            rejected += 1
        else:
            valid_claims.append(claim)
    result.claims = valid_claims
    return result, rejected


def _failed(model: str, error: str) -> dict:
    return {
        "status": "failed",
        "claims": [],
        "empty_reason": None,
        "error": error,
        "input_tokens": 0,
        "output_tokens": 0,
        "cost_estimate": 0.0,
        "prompt_version": PROMPT_VERSION,
        "model": model,
    }
