"""Pydantic request/response schemas for Phase 4A API."""

from __future__ import annotations
import datetime
from typing import Any
from pydantic import BaseModel, field_validator


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------

class RunRequest(BaseModel):
    limit: int | None = None


class RunResponse(BaseModel):
    run_id: str
    status: str


# ---------------------------------------------------------------------------
# Cases
# ---------------------------------------------------------------------------

class FieldComparisonOut(BaseModel):
    field_name: str
    anchor_value: str | None
    new_value: str | None
    result: str  # similar|differs|unknown


class AffectedItemOut(BaseModel):
    paper_id: str
    score: float | None
    score_components: dict | None
    relation: str | None


class AuditEventOut(BaseModel):
    actor: str
    event: str
    detail: str | None
    created_at: datetime.datetime


class CaseListItem(BaseModel):
    id: str
    label: str
    confidence: str | None
    priority_score: float | None
    state: str
    needs_human_attention: bool
    skeptic_verdict: str | None


class ClaimOut(BaseModel):
    id: str
    claim_text: str
    source_sentence: str
    paper_id: str
    paper_title: str | None
    direction: str | None
    population: str | None
    design: str | None
    outcome_measure: str | None
    sample_size: int | None
    country_or_setting: str | None
    follow_up: str | None


class DecisionOut(BaseModel):
    action: str
    reason: str
    decided_by: str
    decided_at: datetime.datetime
    flagged_paper_ids: list[str]


class EvidenceTimelineItem(BaseModel):
    year: int | None
    paper_id: str
    title: str | None
    relation: str | None


NEXT_STEP_BY_LABEL: dict[str, str] = {
    "confirms": "This finding confirms the anchor claim. Consider no further action or flag as supporting evidence.",
    "extends": "This finding extends the anchor claim. Verify the new population/design is genuinely additive.",
    "differs_in_context": "Context differs. Check population and setting fields before deciding.",
    "possible_reproducibility_concern": "Check that population and design really match before deciding.",
    "retraction_impact": "Verify the integrity notice exists and contact the author if confirmed.",
    "insufficient_information": "Too many unknown fields to classify. Seek the full text before deciding.",
    "unrelated": "Claims are unrelated. No action required.",
}


class CaseDetail(BaseModel):
    id: str
    label: str
    confidence: str | None
    rationale: str | None
    priority_score: float | None
    state: str
    needs_human_attention: bool
    skeptic_verdict: str | None
    alternative_label: str | None
    skeptic_argument: str | None
    anchor_claim: ClaimOut | None
    new_claim: ClaimOut | None
    field_comparisons: list[FieldComparisonOut]
    affected_items: list[AffectedItemOut]
    audit_events: list[AuditEventOut]
    decision: DecisionOut | None
    has_integrity_notice: bool
    evidence_timeline: list[EvidenceTimelineItem] = []
    next_step: str = ""


# ---------------------------------------------------------------------------
# Decision
# ---------------------------------------------------------------------------

VALID_ACTIONS = {"no_action", "expert_review", "author_contact", "flag_for_update"}


class DecisionRequest(BaseModel):
    action: str
    reason: str
    decided_by: str
    flagged_paper_ids: list[str] = []

    @field_validator("reason")
    @classmethod
    def reason_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("reason must not be empty")
        return v

    @field_validator("action")
    @classmethod
    def valid_action(cls, v: str) -> str:
        if v not in VALID_ACTIONS:
            raise ValueError(f"action must be one of {VALID_ACTIONS}")
        return v


# ---------------------------------------------------------------------------
# Copilot
# ---------------------------------------------------------------------------

VALID_PRESETS = {"why_label", "what_differs", "draft_context_note", "summarise_for_manager", "what_to_check_next"}


class CopilotRequest(BaseModel):
    preset: str | None = None
    question: str | None = None

    @field_validator("preset")
    @classmethod
    def valid_preset(cls, v: str | None) -> str | None:
        if v and v not in VALID_PRESETS:
            raise ValueError(f"preset must be one of {VALID_PRESETS}")
        return v


class CopilotResponse(BaseModel):
    answer: str
    type: str = "AI draft"


# ---------------------------------------------------------------------------
# Assessment
# ---------------------------------------------------------------------------

class AssessmentOut(BaseModel):
    population_match: str  # similar|differs|unknown
    design_match: str
    outcome_match: str
    relative_sample_strength: str  # stronger|weaker|similar|unknown
    integrity_risk: str  # none|low|high


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

class StatsOut(BaseModel):
    by_label: dict[str, int]
    by_state: dict[str, int]
    decided_count: int
    total_cases: int
    revision_items: int


# ---------------------------------------------------------------------------
# Shared error
# ---------------------------------------------------------------------------

class ErrorDetail(BaseModel):
    error: str
    detail: Any = None
