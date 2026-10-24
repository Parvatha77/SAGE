"""Use Case 2: Evidence-to-Impact Agent API endpoints."""

import json
import logging
import threading
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, func

from ...db import session_scope, create_all
from ...models import (
    AuditEvent, Brief, BriefCheck, Case, Claim, CoverageGap,
    CurrencyCheck, ContextFit, NeedMatch, Need, Outcome,
    Paper, SubmissionRecord,
)
from ...uc2.needs_loader import load_needs, NEEDS_FILE
from ...uc2.nodes import _run_checks

router = APIRouter(prefix="/needs", tags=["needs"])
logger = logging.getLogger(__name__)

_run_status: dict[str, dict] = {}  # run_id -> {status, need_id, error?}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_need_or_404(need_id: str, s) -> Need:
    need = s.get(Need, need_id)
    if not need:
        raise HTTPException(status_code=404, detail="Need not found")
    return need


def _need_detail(need_id: str) -> dict:
    with session_scope() as s:
        need = _get_need_or_404(need_id, s)
        matches_raw = s.execute(
            select(NeedMatch).where(NeedMatch.need_id == need_id)
        ).scalars().all()
        matches_out = []
        for nm in matches_raw:
            cc = s.execute(
                select(CurrencyCheck).where(CurrencyCheck.need_match_id == nm.id)
            ).scalars().first()
            cf = s.execute(
                select(ContextFit).where(ContextFit.need_match_id == nm.id)
            ).scalars().first()
            claim = s.get(Claim, nm.claim_id)
            paper = s.get(Paper, nm.paper_id)
            matches_out.append({
                "id": nm.id,
                "claim_id": nm.claim_id,
                "claim_text": claim.claim_text if claim else None,
                "source_sentence": claim.source_sentence if claim else None,
                "paper_id": nm.paper_id,
                "paper_title": paper.title if paper else None,
                "paper_year": paper.publication_year if paper else None,
                "fit_score": nm.fit_score,
                "fit_reason": nm.fit_reason,
                "included": nm.included,
                "currency_status": cc.status if cc else None,
                "currency_note": cc.note if cc else None,
                "source_case_id": cc.source_case_id if cc else None,
                "context_fit_level": cf.level if cf else None,
                "context_fit_notes": json.loads(cf.field_notes_json) if cf and cf.field_notes_json else {},
            })

        brief_row = s.execute(
            select(Brief).where(Brief.need_id == need_id)
            .order_by(Brief.version.desc())
        ).scalars().first()
        brief_out = None
        checks_out = []
        readiness = None
        if brief_row:
            checks = s.execute(
                select(BriefCheck).where(BriefCheck.brief_id == brief_row.id)
            ).scalars().all()
            checks_out = [
                {"check_name": c.check_name, "passed": c.passed, "detail": c.detail}
                for c in checks
            ]
            passed = sum(1 for c in checks if c.passed)
            checks_score = (passed / len(checks) * 50) if checks else 0
            included = [nm for nm in matches_raw if nm.included]
            used_ids = set(json.loads(brief_row.claim_ids_json))
            fit_scores = [nm.fit_score for nm in included if nm.claim_id in used_ids]
            fit_avg = (sum(fit_scores) / len(fit_scores)) if fit_scores else 0.0
            readiness = round(checks_score + fit_avg * 50, 1)
            brief_out = {
                "id": brief_row.id,
                "version": brief_row.version,
                "text": brief_row.text,
                "claim_ids": json.loads(brief_row.claim_ids_json),
                "status": brief_row.status,
                "approved_by": brief_row.approved_by,
                "approved_at": str(brief_row.approved_at) if brief_row.approved_at else None,
                "created_at": str(brief_row.created_at),
            }

        gap = s.execute(
            select(CoverageGap).where(CoverageGap.need_id == need_id)
            .order_by(CoverageGap.created_at.desc())
        ).scalars().first()
        gap_out = None
        if gap:
            gap_out = {"id": gap.id, "reason": gap.reason,
                       "idea_text": gap.idea_text, "status": gap.status}

        audit = s.execute(
            select(AuditEvent).where(AuditEvent.need_id == need_id)
            .order_by(AuditEvent.created_at)
        ).scalars().all()
        audit_out = [
            {"actor": e.actor, "event": e.event, "detail": e.detail,
             "created_at": str(e.created_at)}
            for e in audit
        ]

        return {
            "id": need.id,
            "title": need.title,
            "source_name": need.source_name,
            "source_url": need.source_url,
            "need_text": need.need_text,
            "audience": need.audience,
            "jurisdiction": need.jurisdiction,
            "deadline": need.deadline,
            "topic_keywords": json.loads(need.topic_keywords_json),
            "population_of_interest": need.population_of_interest,
            "setting_of_interest": need.setting_of_interest,
            "is_example": need.is_example,
            "state": need.state,
            "thread_id": need.thread_id,
            "created_at": str(need.created_at),
            "matches": matches_out,
            "brief": brief_out,
            "checks": checks_out,
            "readiness_score": readiness,
            "gap": gap_out,
            "audit_trail": audit_out,
        }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("")
def list_needs():
    with session_scope() as s:
        needs = s.execute(select(Need).order_by(Need.created_at.desc())).scalars().all()
        return [
            {
                "id": n.id, "title": n.title, "state": n.state,
                "is_example": n.is_example, "jurisdiction": n.jurisdiction,
                "deadline": n.deadline, "created_at": str(n.created_at),
            }
            for n in needs
        ]


@router.post("/import")
def import_needs(path: str | None = None):
    """Load needs.json into the DB. Only imports; never overwrites existing rows."""
    create_all()
    p = Path(path) if path else NEEDS_FILE
    needs = load_needs(p)
    imported = 0
    with session_scope() as s:
        for n in needs:
            if s.get(Need, n.id):
                continue
            s.add(Need(
                id=n.id,
                title=n.title,
                source_name=n.source_name,
                source_url=n.source_url,
                need_text=n.need_text,
                audience=n.audience,
                jurisdiction=n.jurisdiction,
                deadline=n.deadline,
                topic_keywords_json=json.dumps(n.topic_keywords),
                population_of_interest=n.population_of_interest,
                setting_of_interest=n.setting_of_interest,
                is_example=n.is_example,
            ))
            imported += 1
    return {"imported": imported, "total_in_file": len(needs)}


@router.get("/{need_id}")
def get_need(need_id: str):
    with session_scope() as s:
        _get_need_or_404(need_id, s)
    return _need_detail(need_id)


@router.post("/{need_id}/run")
def run_need(need_id: str):
    """Run the graph up to the approval gate in a background thread."""
    with session_scope() as s:
        need = _get_need_or_404(need_id, s)
        if need.state in ("running", "awaiting_approval", "approved", "submitted"):
            raise HTTPException(status_code=409,
                                detail=f"Need is already in state '{need.state}'")

    run_id = str(uuid.uuid4())
    thread_id = str(uuid.uuid4())
    _run_status[run_id] = {"status": "running", "need_id": need_id}

    def _run():
        try:
            import tempfile, os
            from langgraph.checkpoint.sqlite import SqliteSaver
            from ...uc2.graph import build_uc2_graph

            cp_path = Path(__file__).parent.parent.parent.parent / f"uc2_cp_{need_id}.db"
            initial_state: dict = {
                "need_id": need_id,
                "need_thread_id": thread_id,
                "run_id": run_id,
                "stage": "need_intake",
                "matches": [],
                "errors": [],
            }
            config = {"configurable": {"thread_id": thread_id}}

            with session_scope() as s:
                need = s.get(Need, need_id)
                need.thread_id = thread_id

            with SqliteSaver.from_conn_string(str(cp_path)) as cp:
                g = build_uc2_graph().compile(checkpointer=cp)
                list(g.stream(initial_state, config))

            with session_scope() as s:
                need = s.get(Need, need_id)
                if need.state == "running":
                    need.state = "awaiting_approval"

            _run_status[run_id] = {"status": "awaiting_approval", "need_id": need_id}
        except Exception as exc:
            logger.error("UC2 run failed: %s", exc)
            _run_status[run_id] = {"status": "error", "need_id": need_id, "error": str(exc)}

    threading.Thread(target=_run, daemon=True).start()
    return {"run_id": run_id, "thread_id": thread_id, "status": "running"}


@router.get("/runs/{run_id}")
def get_run(run_id: str):
    status = _run_status.get(run_id)
    if status is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return status


class MatchIncludeBody(BaseModel):
    included: bool
    reason: str


@router.post("/{need_id}/matches/{match_id}/include")
def set_match_included(need_id: str, match_id: str, body: MatchIncludeBody):
    with session_scope() as s:
        _get_need_or_404(need_id, s)
        nm = s.get(NeedMatch, match_id)
        if not nm or nm.need_id != need_id:
            raise HTTPException(status_code=404, detail="Match not found")
        cc = s.execute(
            select(CurrencyCheck).where(CurrencyCheck.need_match_id == match_id)
        ).scalars().first()
        if cc and cc.status in ("retracted", "challenged"):
            raise HTTPException(status_code=422,
                                detail=f"Cannot include a {cc.status} match")
        nm.included = body.included
        s.add(AuditEvent(need_id=need_id, actor="editor", event="match_toggled",
                         detail=f"match={match_id[:8]} included={body.included} reason={body.reason[:80]}"))
    return {"match_id": match_id, "included": body.included}


@router.post("/{need_id}/brief/regenerate")
def regenerate_brief(need_id: str):
    from ...uc2.nodes import node_brief_writer, node_brief_checker
    with session_scope() as s:
        need = _get_need_or_404(need_id, s)
    state: dict = {"need_id": need_id, "errors": []}
    state = {**state, **node_brief_writer(state)}
    if state.get("stage") == "error":
        raise HTTPException(status_code=500, detail="; ".join(state.get("errors", [])))
    state = {**state, **node_brief_checker(state)}
    return _need_detail(need_id)


class BriefEditBody(BaseModel):
    text: str


@router.put("/{need_id}/brief")
def edit_brief(need_id: str, body: BriefEditBody):
    with session_scope() as s:
        _get_need_or_404(need_id, s)
        brief = s.execute(
            select(Brief).where(Brief.need_id == need_id)
            .order_by(Brief.version.desc())
        ).scalars().first()
        if not brief:
            raise HTTPException(status_code=404, detail="No brief to edit")
        brief.text = body.text
        brief_id = brief.id
        s.add(AuditEvent(need_id=need_id, actor="editor", event="brief_edited"))

    checks, readiness = _run_checks(brief_id, need_id)
    with session_scope() as s:
        # Clear old checks
        old = s.execute(
            select(BriefCheck).where(BriefCheck.brief_id == brief_id)
        ).scalars().all()
        for c in old:
            s.delete(c)
        for c in checks:
            s.add(BriefCheck(brief_id=brief_id, check_name=c["name"],
                             passed=c["passed"], detail=c["detail"]))

    return {"brief_id": brief_id, "readiness_score": readiness,
            "checks": checks}


class ApproveBody(BaseModel):
    approver: str
    reason: str | None = None


class RejectBody(BaseModel):
    reason: str


def _resume_graph(need_id: str, decision: dict):
    """Resume the LangGraph approval_gate interrupt."""
    from langgraph.checkpoint.sqlite import SqliteSaver
    from langgraph.types import Command
    from ...uc2.graph import build_uc2_graph

    with session_scope() as s:
        need = s.get(Need, need_id)
        thread_id = need.thread_id if need else None

    if not thread_id:
        return

    cp_path = Path(__file__).parent.parent.parent.parent / f"uc2_cp_{need_id}.db"
    config = {"configurable": {"thread_id": thread_id}}
    with SqliteSaver.from_conn_string(str(cp_path)) as cp:
        g = build_uc2_graph().compile(checkpointer=cp)
        list(g.stream(Command(resume=decision), config))


@router.post("/{need_id}/approve")
def approve_need(need_id: str, body: ApproveBody):
    with session_scope() as s:
        need = _get_need_or_404(need_id, s)
        if need.state != "awaiting_approval":
            raise HTTPException(status_code=409,
                                detail=f"Need is in state '{need.state}', not awaiting_approval")

    decision = {"action": "approved", "approver": body.approver, "reason": body.reason or ""}
    _resume_graph(need_id, decision)
    return _need_detail(need_id)


@router.post("/{need_id}/reject")
def reject_need(need_id: str, body: RejectBody):
    if not body.reason:
        raise HTTPException(status_code=422, detail="Rejection requires a reason")
    with session_scope() as s:
        need = _get_need_or_404(need_id, s)
        if need.state != "awaiting_approval":
            raise HTTPException(status_code=409,
                                detail=f"Need is in state '{need.state}', not awaiting_approval")

    decision = {"action": "rejected", "reason": body.reason}
    _resume_graph(need_id, decision)
    return _need_detail(need_id)


class SubmitBody(BaseModel):
    submitted_by: str
    channel_note: str | None = None


@router.post("/{need_id}/submit")
def submit_need(need_id: str, body: SubmitBody):
    with session_scope() as s:
        need = _get_need_or_404(need_id, s)
        if need.state != "approved":
            raise HTTPException(status_code=409,
                                detail="Cannot submit: brief not yet approved")
        brief = s.execute(
            select(Brief).where(Brief.need_id == need_id, Brief.status == "approved")
        ).scalars().first()
        if not brief:
            raise HTTPException(status_code=409, detail="No approved brief found")

        need.state = "submitted"
        brief.status = "submitted"
        s.add(SubmissionRecord(brief_id=brief.id, submitted_by=body.submitted_by,
                               channel_note=body.channel_note))
        s.add(AuditEvent(need_id=need_id, actor=body.submitted_by, event="brief_submitted",
                         detail=body.channel_note))
    return {"status": "submitted"}


class OutcomeBody(BaseModel):
    outcome: str   # cited|acknowledged|no_visible_use
    note: str | None = None


@router.post("/{need_id}/outcome")
def record_outcome(need_id: str, body: OutcomeBody):
    if body.outcome not in ("cited", "acknowledged", "no_visible_use"):
        raise HTTPException(status_code=422, detail="Invalid outcome value")

    with session_scope() as s:
        need = _get_need_or_404(need_id, s)
        if need.state != "submitted":
            raise HTTPException(status_code=409,
                                detail="Cannot record outcome: need has not been submitted")
        brief = s.execute(
            select(Brief).where(Brief.need_id == need_id, Brief.status == "submitted")
        ).scalars().first()
        if not brief:
            raise HTTPException(status_code=409, detail="No submitted brief found")

    # LLM impact summary
    impact_summary = _draft_impact_summary(need_id, body.outcome, body.note or "")

    with session_scope() as s:
        brief = s.execute(
            select(Brief).where(Brief.need_id == need_id, Brief.status == "submitted")
        ).scalars().first()
        need = s.get(Need, need_id)
        need.state = "outcome_recorded"
        brief.status = "outcome_recorded"
        s.add(Outcome(brief_id=brief.id, outcome=body.outcome,
                      note=body.note, impact_summary=impact_summary))
        s.add(AuditEvent(need_id=need_id, actor="editor", event="outcome_recorded",
                         detail=f"outcome={body.outcome}"))

    return {"outcome": body.outcome, "impact_summary": impact_summary}


def _draft_impact_summary(need_id: str, outcome: str, note: str) -> str:
    from ...llm import get_provider
    from ...extraction.prompts import PROMPT_VERSION
    with session_scope() as s:
        need = s.get(Need, need_id)
        brief = s.execute(
            select(Brief).where(Brief.need_id == need_id)
            .order_by(Brief.version.desc())
        ).scalars().first()
    provider = get_provider()
    system = "Draft a 2-sentence plain-language impact summary. Output JSON: {\"summary\": \"...\"}"
    user = (
        f"NEED: {need.title}\n"
        f"OUTCOME: {outcome}\n"
        f"NOTE: {note}\n"
        f"BRIEF (first 300 chars): {brief.text[:300] if brief else ''}"
    )
    try:
        raw = provider.complete_json(system=system, user=user,
                                     prompt_version=f"uc2-impact-{PROMPT_VERSION}")
        return raw.get("summary", "Impact recorded.")
    except Exception:
        return "Impact recorded."


class GapSendBody(BaseModel):
    note: str | None = None


@router.post("/{need_id}/gap/send")
def send_gap(need_id: str, body: GapSendBody):
    with session_scope() as s:
        _get_need_or_404(need_id, s)
        gap = s.execute(
            select(CoverageGap).where(CoverageGap.need_id == need_id,
                                      CoverageGap.status == "open")
        ).scalars().first()
        if not gap:
            raise HTTPException(status_code=404, detail="No open gap found")
        gap.status = "sent_to_editors"
        s.add(AuditEvent(need_id=need_id, actor="editor", event="gap_sent",
                         detail=body.note))
    return {"gap_id": gap.id, "status": "sent_to_editors"}


class CopilotBody(BaseModel):
    question: str | None = None
    preset: str | None = None


COPILOT_PRESETS = {
    "strongest_evidence": "Which claim in this need's evidence set has the strongest fit? Quote its source sentence.",
    "explain_in_3_lines": "Summarise the key finding for this need in exactly 3 plain-English lines.",
    "questions_to_expect": "What 3 questions might a policymaker ask after reading this brief? Answer each briefly.",
    "risks_and_limits": "What are the main risks and limits of using this evidence for the stated policy need?",
}


@router.post("/{need_id}/copilot")
def copilot(need_id: str, body: CopilotBody):
    from ...llm import get_provider
    from ...extraction.prompts import PROMPT_VERSION

    question = body.question or (COPILOT_PRESETS.get(body.preset or "") if body.preset else None)
    if not question:
        raise HTTPException(status_code=422, detail="Provide a preset or question")

    detail = _need_detail(need_id)
    context = (
        f"NEED: {detail['title']}\n"
        f"NEED TEXT: {detail['need_text']}\n\n"
        "MATCHES:\n" + "\n".join(
            f"- [{m['currency_status']}] {m['source_sentence']} (fit={m['fit_score']})"
            for m in detail["matches"] if m["included"]
        ) + "\n\n"
        f"BRIEF:\n{detail['brief']['text'] if detail.get('brief') else '(not yet written)'}"
    )
    system = (
        "You are an evidence copilot. Use ONLY the data provided. "
        "Quote source sentences directly. "
        "If data is insufficient, say 'not enough information in this case'. "
        "Return text only. Never change any data."
    )
    user = f"{context}\n\nQUESTION: {question}"

    provider = get_provider()
    try:
        raw = provider.complete_json(system=system, user=user,
                                     prompt_version=f"uc2-copilot-{PROMPT_VERSION}")
        answer = raw.get("answer") or raw.get("response") or str(raw)
    except Exception as exc:
        answer = f"Copilot unavailable: {exc}"

    with session_scope() as s:
        s.add(AuditEvent(need_id=need_id, actor="copilot", event="copilot_query",
                         detail=f"preset={body.preset} q={question[:80]}"))

    return {"answer": answer, "type": "AI draft"}


@router.get("/{need_id}/assessment")
def get_assessment(need_id: str):
    detail = _need_detail(need_id)
    matches = detail["matches"]
    included = [m for m in matches if m["included"]]

    avg_fit = round(sum(m["fit_score"] for m in included) / len(included), 3) if included else 0.0
    context_levels = [m["context_fit_level"] for m in included if m["context_fit_level"]]
    good_ctx = sum(1 for l in context_levels if l == "good")
    avg_context = (
        "good" if good_ctx >= len(context_levels) * 0.6
        else "partial" if good_ctx >= len(context_levels) * 0.3
        else "poor" if context_levels else "unknown"
    )
    currency_statuses = [m["currency_status"] for m in matches]
    challenged = sum(1 for s in currency_statuses if s in ("retracted", "challenged", "under_review"))
    currency_risk = "high" if challenged >= 2 else "medium" if challenged == 1 else "low"

    checks = detail["checks"]
    checks_passed = sum(1 for c in checks if c["passed"])
    checks_total = len(checks)

    return {
        "avg_fit_score": avg_fit,
        "context_match": avg_context,
        "currency_risk": currency_risk,
        "challenged_dropped": challenged,
        "checks_passed": checks_passed,
        "checks_total": checks_total,
        "readiness_score": detail["readiness_score"],
    }
