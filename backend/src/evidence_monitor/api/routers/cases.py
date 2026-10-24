"""Case endpoints: GET /cases, GET /cases/{id}, POST /cases/{id}/decision, copilot, assessment."""

import json
import logging

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from ...db import session_scope
from ...models import (
    AffectedItem, AuditEvent, Case, Claim, ClaimPair,
    Decision, FieldComparison, IntegrityNotice, Paper, RevisionItem,
)
from ..schemas import (
    AssessmentOut, CaseDetail, CaseListItem, ClaimOut, CopilotRequest,
    CopilotResponse, DecisionOut, DecisionRequest, FieldComparisonOut,
    AffectedItemOut, AuditEventOut, EvidenceTimelineItem, NEXT_STEP_BY_LABEL,
)

router = APIRouter(prefix="/cases", tags=["cases"])
logger = logging.getLogger(__name__)


def _get_case_or_404(case_id: str, session) -> Case:
    case = session.get(Case, case_id)
    if not case:
        case = session.execute(
            select(Case).where(Case.id.like(f"{case_id}%"))
        ).scalars().first()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    return case


def _claim_out(claim: Claim | None, session) -> ClaimOut | None:
    if not claim:
        return None
    paper = session.get(Paper, claim.paper_id)
    return ClaimOut(
        id=claim.id,
        claim_text=claim.claim_text,
        source_sentence=claim.source_sentence,
        paper_id=claim.paper_id,
        paper_title=paper.title if paper else None,
        direction=claim.direction,
        population=claim.population,
        design=claim.design,
        outcome_measure=claim.outcome_measure,
        sample_size=claim.sample_size,
        country_or_setting=claim.country_or_setting,
        follow_up=claim.follow_up,
    )


@router.get("", response_model=list[CaseListItem])
def list_cases(
    label: str | None = Query(None),
    priority_min: float | None = Query(None),
    state: str | None = Query(None),
    attention: bool = Query(False),
    category: str | None = Query(None),
):
    with session_scope() as s:
        q = select(Case).where(Case.label != "unrelated").order_by(Case.priority_score.desc())

        if category and category != "all":
            # Filter by category based on anchor claim's paper_id pattern
            if category == "demo":
                # Show only demo cases (paper_id starts with DEMO-)
                anchor = select(Claim.id).where(Claim.paper_id.like("DEMO-%"))
                q = q.where(Case.anchor_claim_id.in_(anchor))
            elif category == "Education":
                anchor = select(Claim.id).where(Claim.paper_id.like("DEMO-Education%"))
                q = q.where(Case.anchor_claim_id.in_(anchor))
            elif category == "MentalHealth":
                anchor = select(Claim.id).where(Claim.paper_id.like("DEMO-Mental%"))
                q = q.where(Case.anchor_claim_id.in_(anchor))
            elif category == "Science":
                anchor = select(Claim.id).where(Claim.paper_id.like("DEMO-Evidence%"))
                q = q.where(Case.anchor_claim_id.in_(anchor))
            else:
                # Fallback: try exact category match
                anchor = select(Claim.id).where(Claim.paper_id.like(f"DEMO-{category}-%"))
                q = q.where(Case.anchor_claim_id.in_(anchor))
        elif category == "all":
            # Show all real cases (not demo)
            anchor = select(Claim.id).where(~Claim.paper_id.like("DEMO-%"))
            q = q.where(Case.anchor_claim_id.in_(anchor))

        if label:
            q = q.where(Case.label == label)
        if priority_min is not None:
            q = q.where(Case.priority_score >= priority_min)
        if state:
            q = q.where(Case.state == state)
        if attention:
            q = q.where(Case.needs_human_attention == True)
        cases = s.execute(q).scalars().all()
        return [
            CaseListItem(
                id=c.id,
                label=c.label,
                confidence=c.confidence,
                priority_score=c.priority_score,
                state=c.state,
                needs_human_attention=c.needs_human_attention,
                skeptic_verdict=c.skeptic_verdict,
            )
            for c in cases
        ]


@router.get("/{case_id}", response_model=CaseDetail)
def get_case(case_id: str):
    with session_scope() as s:
        case = _get_case_or_404(case_id, s)

        anchor = s.get(Claim, case.anchor_claim_id) if case.anchor_claim_id else None
        new_claim = s.get(Claim, case.new_claim_id) if case.new_claim_id else None

        pair = None
        if anchor and new_claim:
            pair = s.execute(
                select(ClaimPair).where(
                    ClaimPair.anchor_claim_id == case.anchor_claim_id,
                    ClaimPair.new_claim_id == case.new_claim_id,
                )
            ).scalars().first()

        comparisons = []
        if pair:
            fcs = s.execute(
                select(FieldComparison).where(FieldComparison.claim_pair_id == pair.id)
            ).scalars().all()
            comparisons = [
                FieldComparisonOut(
                    field_name=fc.field_name,
                    anchor_value=fc.anchor_value,
                    new_value=fc.new_value,
                    result=fc.result,
                )
                for fc in fcs
            ]

        affected = s.execute(
            select(AffectedItem).where(AffectedItem.case_id == case.id)
            .order_by(AffectedItem.score.desc())
        ).scalars().all()

        audit = s.execute(
            select(AuditEvent).where(AuditEvent.case_id == case.id)
            .order_by(AuditEvent.created_at)
        ).scalars().all()

        decision_row = s.execute(
            select(Decision).where(Decision.case_id == case.id)
        ).scalars().first()
        decision_out = None
        if decision_row:
            flagged = json.loads(decision_row.flagged_paper_ids_json or "[]")
            decision_out = DecisionOut(
                action=decision_row.action,
                reason=decision_row.reason,
                decided_by=decision_row.decided_by,
                decided_at=decision_row.decided_at,
                flagged_paper_ids=flagged,
            )

        has_notice = bool(case.notice_id)

        # Evidence timeline: anchor + affected papers ordered by publication_year
        timeline_items: list[EvidenceTimelineItem] = []
        seen_paper_ids: set[str] = set()
        for claim_obj, relation in [(anchor, "anchor"), (new_claim, "new")]:
            if claim_obj and claim_obj.paper_id not in seen_paper_ids:
                p = s.get(Paper, claim_obj.paper_id)
                timeline_items.append(EvidenceTimelineItem(
                    year=p.publication_year if p else None,
                    paper_id=claim_obj.paper_id,
                    title=p.title if p else None,
                    relation=relation,
                ))
                seen_paper_ids.add(claim_obj.paper_id)
        for aff in affected:
            if aff.paper_id not in seen_paper_ids:
                p = s.get(Paper, aff.paper_id)
                timeline_items.append(EvidenceTimelineItem(
                    year=p.publication_year if p else None,
                    paper_id=aff.paper_id,
                    title=p.title if p else None,
                    relation=aff.relation,
                ))
                seen_paper_ids.add(aff.paper_id)
        timeline_items.sort(key=lambda x: (x.year or 0))

        # Suggested next step
        if case.needs_human_attention:
            next_step = "This case needs your attention — the skeptic flagged a possible label change."
        else:
            next_step = NEXT_STEP_BY_LABEL.get(case.label, "Review the source sentences and field comparisons, then record a decision.")

        return CaseDetail(
            id=case.id,
            label=case.label,
            confidence=case.confidence,
            rationale=case.rationale,
            priority_score=case.priority_score,
            state=case.state,
            needs_human_attention=case.needs_human_attention,
            skeptic_verdict=case.skeptic_verdict,
            alternative_label=case.alternative_label,
            skeptic_argument=case.skeptic_argument,
            anchor_claim=_claim_out(anchor, s),
            new_claim=_claim_out(new_claim, s),
            field_comparisons=comparisons,
            affected_items=[
                AffectedItemOut(
                    paper_id=a.paper_id,
                    score=a.score,
                    score_components=json.loads(a.score_components_json) if a.score_components_json else None,
                    relation=a.relation,
                )
                for a in affected
            ],
            audit_events=[
                AuditEventOut(actor=e.actor, event=e.event, detail=e.detail, created_at=e.created_at)
                for e in audit
            ],
            decision=decision_out,
            has_integrity_notice=has_notice,
            evidence_timeline=timeline_items,
            next_step=next_step,
        )


@router.post("/{case_id}/decision")
def post_decision(case_id: str, body: DecisionRequest):
    with session_scope() as s:
        case = _get_case_or_404(case_id, s)

        # 409 if already decided
        existing = s.execute(select(Decision).where(Decision.case_id == case.id)).scalars().first()
        if existing:
            raise HTTPException(status_code=409, detail="Decision already recorded for this case")

        # Validate flag_for_update needs paper ids
        if body.action == "flag_for_update" and not body.flagged_paper_ids:
            raise HTTPException(status_code=422, detail="flag_for_update requires at least one flagged_paper_id")

        case.state = "decided"

        s.add(Decision(
            case_id=case.id,
            action=body.action,
            reason=body.reason,
            decided_by=body.decided_by,
            flagged_paper_ids_json=json.dumps(body.flagged_paper_ids) if body.flagged_paper_ids else None,
        ))

        if body.action == "flag_for_update":
            for pid in body.flagged_paper_ids:
                s.add(RevisionItem(case_id=case.id, paper_id=pid, note=body.reason))

        s.add(AuditEvent(
            case_id=case.id,
            actor="editor",
            event="decision_recorded",
            detail=f"action={body.action} decided_by={body.decided_by}",
        ))

    return {"status": "ok", "case_id": case_id, "action": body.action}


@router.post("/{case_id}/draft-author-message")
def draft_author_message(case_id: str):
    with session_scope() as s:
        case = _get_case_or_404(case_id, s)
        anchor = s.get(Claim, case.anchor_claim_id) if case.anchor_claim_id else None
        new = s.get(Claim, case.new_claim_id) if case.new_claim_id else None

        draft = (
            f"[AI DRAFT — do not send without review]\n\n"
            f"Dear Author,\n\n"
            f"We are writing regarding your paper. Our monitoring system has identified a "
            f"case ({case.label}) involving the following claim:\n\n"
            f"Anchor: {anchor.claim_text if anchor else 'unknown'}\n\n"
            f"New finding: {new.claim_text if new else 'unknown'}\n\n"
            f"Rationale: {case.rationale or 'See case details.'}\n\n"
            f"No action is required at this stage. This is an informational note only.\n\n"
            f"[Edit before sending]"
        )

        s.add(AuditEvent(
            case_id=case.id,
            actor="system",
            event="draft_author_message",
            detail="Draft generated (not sent)",
        ))

    return {"draft": draft, "type": "AI draft", "sent": False}


@router.post("/{case_id}/copilot", response_model=CopilotResponse)
def copilot(case_id: str, body: CopilotRequest):
    from ...llm import get_provider
    from ...extraction.prompts import PROMPT_VERSION

    with session_scope() as s:
        case = _get_case_or_404(case_id, s)
        anchor = s.get(Claim, case.anchor_claim_id) if case.anchor_claim_id else None
        new = s.get(Claim, case.new_claim_id) if case.new_claim_id else None
        anchor_paper = s.get(Paper, anchor.paper_id) if anchor else None
        new_paper = s.get(Paper, new.paper_id) if new else None

        pair = None
        if anchor and new:
            pair = s.execute(
                select(ClaimPair).where(
                    ClaimPair.anchor_claim_id == case.anchor_claim_id,
                    ClaimPair.new_claim_id == case.new_claim_id,
                )
            ).scalars().first()

        comparisons = []
        if pair:
            fcs = s.execute(
                select(FieldComparison).where(FieldComparison.claim_pair_id == pair.id)
            ).scalars().all()
            comparisons = fcs

    # Build case context
    comp_lines = "\n".join(
        f"  {fc.field_name}: anchor={fc.anchor_value!r} | new={fc.new_value!r} | result={fc.result}"
        for fc in comparisons
    )
    case_context = (
        f"CASE ID: {case.id}\n"
        f"LABEL: {case.label}\n"
        f"CONFIDENCE: {case.confidence}\n"
        f"RATIONALE: {case.rationale}\n"
        f"SKEPTIC VERDICT: {case.skeptic_verdict}\n"
        f"SKEPTIC ARGUMENT: {case.skeptic_argument}\n\n"
        f"ANCHOR CLAIM ({anchor_paper.title[:60] if anchor_paper else 'unknown'}):\n"
        f"  {anchor.claim_text if anchor else 'N/A'}\n"
        f"  Source: \"{anchor.source_sentence if anchor else ''}\"\n\n"
        f"NEW CLAIM ({new_paper.title[:60] if new_paper else 'unknown'}):\n"
        f"  {new.claim_text if new else 'N/A'}\n"
        f"  Source: \"{new.source_sentence if new else ''}\"\n\n"
        f"FIELD COMPARISONS:\n{comp_lines or '  (none)'}"
    )

    preset_prompts = {
        "why_label": "Explain why this label was assigned. Quote the source sentences.",
        "what_differs": "What specifically differs between the two claims? Quote from the source sentences.",
        "draft_context_note": "Draft a brief context note (2-3 sentences) summarising this case for an editor.",
        "summarise_for_manager": "Summarise this case in plain English for a non-specialist manager.",
        "what_to_check_next": "What should an editor check next to validate or refute this label?",
    }

    question = body.question or (preset_prompts.get(body.preset or "") if body.preset else None)
    if not question:
        raise HTTPException(status_code=422, detail="Provide a preset or question")

    system = (
        "You are a research evidence copilot. You have been given data about ONE case only. "
        "Answer only from the provided case data. Quote source sentences directly. "
        "If the data is insufficient, say 'not enough information in this case' rather than guessing. "
        "Return text only. Never change any case or decision data."
    )
    user = f"{case_context}\n\nQUESTION: {question}"

    provider = get_provider()
    try:
        raw = provider.complete_json(
            system=system,
            user=user,
            prompt_version=f"copilot-{PROMPT_VERSION}",
        )
        answer = raw.get("answer") or raw.get("response") or str(raw)
    except Exception as exc:
        logger.warning("Copilot LLM error: %s", exc)
        answer = "Copilot is unavailable right now. Please try again."

    with session_scope() as s:
        s.add(AuditEvent(
            case_id=case.id,
            actor="copilot",
            event="copilot_query",
            detail=f"preset={body.preset} question={question[:80]}",
        ))

    return CopilotResponse(answer=answer, type="AI draft")


@router.get("/{case_id}/assessment", response_model=AssessmentOut)
def get_assessment(case_id: str):
    with session_scope() as s:
        case = _get_case_or_404(case_id, s)
        anchor = s.get(Claim, case.anchor_claim_id) if case.anchor_claim_id else None
        new = s.get(Claim, case.new_claim_id) if case.new_claim_id else None

        pair = None
        if anchor and new:
            pair = s.execute(
                select(ClaimPair).where(
                    ClaimPair.anchor_claim_id == case.anchor_claim_id,
                    ClaimPair.new_claim_id == case.new_claim_id,
                )
            ).scalars().first()

        fcs: dict[str, str] = {}
        if pair:
            rows = s.execute(
                select(FieldComparison).where(FieldComparison.claim_pair_id == pair.id)
            ).scalars().all()
            fcs = {fc.field_name: fc.result for fc in rows}

        has_notice = bool(case.notice_id)
        anchor_n = anchor.sample_size if anchor else None
        new_n = new.sample_size if new else None

        if anchor_n and new_n:
            if new_n > anchor_n * 1.5:
                rel_strength = "stronger"
            elif new_n < anchor_n * 0.67:
                rel_strength = "weaker"
            else:
                rel_strength = "similar"
        else:
            rel_strength = "unknown"

        if has_notice:
            integrity_risk = "high"
        elif case.label == "retraction_impact":
            integrity_risk = "low"
        else:
            integrity_risk = "none"

    return AssessmentOut(
        population_match=fcs.get("population", "unknown"),
        design_match=fcs.get("design", "unknown"),
        outcome_match=fcs.get("outcome_measure", "unknown"),
        relative_sample_strength=rel_strength,
        integrity_risk=integrity_risk,
    )
