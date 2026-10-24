"""GET /stats, GET /revision-items, GET /impact/stats."""

import datetime
from fastapi import APIRouter
from sqlalchemy import select, func

from ...db import session_scope
from ...models import (
    Case, CoverageGap, CurrencyCheck, Decision, Need, NeedMatch,
    Outcome, RevisionItem, Paper,
)
from ..schemas import StatsOut

router = APIRouter(tags=["stats"])


@router.get("/stats", response_model=StatsOut)
def get_stats():
    with session_scope() as s:
        label_rows = s.execute(
            select(Case.label, func.count()).group_by(Case.label)
        ).all()
        state_rows = s.execute(
            select(Case.state, func.count()).group_by(Case.state)
        ).all()
        decided = s.execute(select(func.count()).select_from(Decision)).scalar() or 0
        total = s.execute(select(func.count()).select_from(Case)).scalar() or 0
        rev_items = s.execute(select(func.count()).select_from(RevisionItem)).scalar() or 0

    return StatsOut(
        by_label={lbl: cnt for lbl, cnt in label_rows},
        by_state={st: cnt for st, cnt in state_rows},
        decided_count=decided,
        total_cases=total,
        revision_items=rev_items,
    )


@router.get("/impact/stats")
def impact_stats():
    with session_scope() as s:
        needs_by_state = {
            row[0]: row[1]
            for row in s.execute(select(Need.state, func.count()).group_by(Need.state)).all()
        }
        briefs_approved = s.execute(
            select(func.count()).select_from(Need)
            .where(Need.state.in_(["approved", "submitted", "outcome_recorded"]))
        ).scalar() or 0
        outcomes_recorded = s.execute(select(func.count()).select_from(Outcome)).scalar() or 0
        open_gaps = s.execute(
            select(func.count()).select_from(CoverageGap)
            .where(CoverageGap.status == "open")
        ).scalar() or 0
        challenged = s.execute(
            select(func.count()).select_from(CurrencyCheck)
            .where(CurrencyCheck.status.in_(["retracted", "challenged", "under_review"]))
        ).scalar() or 0
        # Coverage gaps by first keyword of each need
        gaps = s.execute(select(CoverageGap)).scalars().all()
        gap_by_topic: dict[str, int] = {}
        for g in gaps:
            need = s.get(Need, g.need_id)
            if need:
                import json as _json
                kws = _json.loads(need.topic_keywords_json)
                key = kws[0] if kws else "unknown"
                gap_by_topic[key] = gap_by_topic.get(key, 0) + 1

    return {
        "needs_by_state": needs_by_state,
        "briefs_approved": briefs_approved,
        "outcomes_recorded": outcomes_recorded,
        "open_gaps": open_gaps,
        "challenged_dropped": challenged,
        "coverage_gaps_by_topic": gap_by_topic,
    }


@router.get("/revision-items")
def list_revision_items():
    with session_scope() as s:
        items = s.execute(
            select(RevisionItem).order_by(RevisionItem.created_at.desc())
        ).scalars().all()
        return [
            {
                "id": item.id,
                "case_id": item.case_id,
                "paper_id": item.paper_id,
                "where_text": item.where_text,
                "note": item.note,
                "created_at": item.created_at,
            }
            for item in items
        ]
