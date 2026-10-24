"""LangGraph state schema for the case agent."""

from typing import Annotated, Any
from typing_extensions import TypedDict
import operator


class CaseState(TypedDict):
    case_id: str | None
    anchor_claim_id: str | None
    run_id: str | None
    stage: str
    label: str | None
    confidence: str | None
    rationale: str | None
    skeptic_verdict: str | None
    needs_human_attention: bool
    affected_items: list[dict]
    errors: Annotated[list[str], operator.add]
    # Set by review_gate interrupt resume
    decision: dict | None
