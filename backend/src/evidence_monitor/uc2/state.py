"""LangGraph state for the Evidence-to-Impact Agent (UC2)."""

from typing import TypedDict, Any


class UC2State(TypedDict, total=False):
    need_id: str
    need_thread_id: str | None
    run_id: str | None
    stage: str
    matches: list[dict]          # NeedMatch dicts with currency/context attached
    brief_id: str | None
    brief_text: str | None
    readiness_score: float | None
    gap_id: str | None
    errors: list[str]
    decision: dict | None        # approval/rejection payload from interrupt()
