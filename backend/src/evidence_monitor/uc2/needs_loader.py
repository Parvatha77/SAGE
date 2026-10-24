"""Load and validate needs from data/needs.json."""

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, field_validator, model_validator

NEEDS_FILE = Path(__file__).parent.parent.parent.parent / "data" / "needs.json"


class NeedSchema(BaseModel):
    id: str
    title: str
    source_name: str
    source_url: str | None = None
    need_text: str
    audience: str
    jurisdiction: str
    deadline: str | None = None
    topic_keywords: list[str]
    population_of_interest: str
    setting_of_interest: str
    is_example: bool

    @field_validator("title", "need_text", "audience", "jurisdiction", "source_name")
    @classmethod
    def not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("must not be empty")
        return v

    @field_validator("topic_keywords")
    @classmethod
    def keywords_not_empty(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("topic_keywords must contain at least one keyword")
        return v


def load_needs(path: Path | None = None) -> list[NeedSchema]:
    """Parse and validate needs.json; raise ValueError on any schema error."""
    p = path or NEEDS_FILE
    if not p.exists():
        raise FileNotFoundError(f"needs.json not found at {p}")
    raw: list[Any] = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("needs.json must be a JSON array")
    needs = []
    for i, item in enumerate(raw):
        try:
            needs.append(NeedSchema.model_validate(item))
        except Exception as exc:
            raise ValueError(f"needs.json item {i}: {exc}") from exc
    return needs
