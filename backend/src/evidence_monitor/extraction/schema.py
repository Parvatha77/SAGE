"""Pydantic models for extracted claims."""

from typing import Literal

from pydantic import BaseModel, Field, model_validator


DETAIL_FIELDS = [
    "effect_reported",
    "population",
    "country_or_setting",
    "design",
    "outcome_measure",
    "sample_size",
    "sample_size_text",
    "follow_up",
]


class ClaimData(BaseModel):
    claim_text: str = Field(description="One plain sentence stating the finding, neutral wording.")
    source_sentence: str = Field(description="Exact sentence copied from the abstract.")
    direction: Literal["positive", "negative", "null_effect", "mixed", "descriptive"] | None = None
    effect_reported: str | None = None
    population: str | None = None
    country_or_setting: str | None = None
    design: str | None = None
    outcome_measure: str | None = None
    sample_size: int | None = None
    sample_size_text: str | None = None
    follow_up: str | None = None
    is_primary_claim: bool = True
    extraction_confidence: Literal["high", "medium", "low"] | None = None
    confidence_note: str | None = None
    fields_missing: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def compute_fields_missing(self) -> "ClaimData":
        missing = [f for f in DETAIL_FIELDS if getattr(self, f) is None]
        self.fields_missing = missing
        return self


class ExtractionResult(BaseModel):
    claims: list[ClaimData] = Field(default_factory=list)
    empty_reason: str | None = Field(
        default=None,
        description="If claims is empty, explain why (e.g. 'editorial', 'no empirical finding').",
    )
