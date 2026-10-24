"""LangGraph node functions — thin wrappers around existing pipeline functions."""

import json
import logging

from langgraph.types import interrupt

from ..db import session_scope
from ..models import AuditEvent, Case, Decision, RevisionItem
from ..run_events import emit as _emit
from .state import CaseState

logger = logging.getLogger(__name__)


def _audit(case_id: str | None, run_id: str | None, actor: str, event: str, detail: str = "") -> None:
    with session_scope() as s:
        s.add(AuditEvent(case_id=case_id, run_id=run_id, actor=actor, event=event, detail=detail))


# ---------------------------------------------------------------------------
# Node 1: discovery
# ---------------------------------------------------------------------------

def node_discovery(state: CaseState) -> dict:
    from ..comparison.candidates import build_embeddings, find_candidates
    run_id = state.get("run_id") or ""
    _emit(run_id, "discovery", "started", "Building claim embeddings and finding candidate pairs")
    try:
        import time; t0 = time.monotonic()
        build_embeddings()
        new_pairs = find_candidates(limit=None)
        ms = int((time.monotonic() - t0) * 1000)
        _emit(run_id, "discovery", "finished",
              f"Found {new_pairs} new candidate pairs to compare",
              counters={"pairs_found": new_pairs}, duration_ms=ms)
        _audit(None, run_id, "system", "discovery_complete", f"new_pairs={new_pairs}")
        return {"stage": "evidence"}
    except Exception as exc:
        _emit(run_id, "discovery", "failed", f"Discovery failed: {exc}")
        return {"errors": [f"discovery: {exc}"], "stage": "evidence"}


# ---------------------------------------------------------------------------
# Node 2: evidence (relevance + field compare + classify)
# ---------------------------------------------------------------------------

def node_evidence(state: CaseState) -> dict:
    from ..comparison.compare import compare_all
    from ..comparison.classify import classify_all
    run_id = state.get("run_id") or ""
    _emit(run_id, "evidence", "started", "Comparing fields and classifying claim pairs")
    try:
        import time; t0 = time.monotonic()
        compare_all()
        created = classify_all()
        ms = int((time.monotonic() - t0) * 1000)
        _emit(run_id, "evidence", "finished",
              f"Classified pairs, created {created} cases",
              counters={"cases_created": created}, duration_ms=ms)
        _audit(None, run_id, "system", "evidence_complete", f"cases_created={created}")
        return {"stage": "integrity"}
    except Exception as exc:
        _emit(run_id, "evidence", "failed", f"Evidence step failed: {exc}")
        return {"errors": [f"evidence: {exc}"], "stage": "integrity"}


# ---------------------------------------------------------------------------
# Node 3: integrity
# ---------------------------------------------------------------------------

def node_integrity(state: CaseState) -> dict:
    from sqlalchemy import select
    from ..models import IntegrityNotice, Claim
    run_id = state.get("run_id") or ""
    _emit(run_id, "integrity", "started", "Linking retraction and integrity notices to cases")
    try:
        import time; t0 = time.monotonic()
        with session_scope() as s:
            from ..models import Case as CaseModel
            cases = s.execute(select(CaseModel).where(CaseModel.notice_id.is_(None))).scalars().all()
            linked = 0
            for case in cases:
                anchor = s.get(Claim, case.anchor_claim_id)
                if anchor:
                    notice = s.execute(
                        select(IntegrityNotice).where(IntegrityNotice.paper_id == anchor.paper_id)
                    ).scalars().first()
                    if notice:
                        case.notice_id = notice.id
                        linked += 1
        ms = int((time.monotonic() - t0) * 1000)
        _emit(run_id, "integrity", "finished",
              f"Linked {linked} integrity notices to cases",
              counters={"notices_linked": linked}, duration_ms=ms)
        _audit(None, run_id, "system", "integrity_complete", f"linked={linked}")
        return {"stage": "skeptic"}
    except Exception as exc:
        _emit(run_id, "integrity", "failed", f"Integrity step failed: {exc}")
        return {"errors": [f"integrity: {exc}"], "stage": "skeptic"}


# ---------------------------------------------------------------------------
# Node 4: skeptic
# ---------------------------------------------------------------------------

def node_skeptic(state: CaseState) -> dict:
    from ..comparison.skeptic import run_skeptic_all
    run_id = state.get("run_id") or ""
    _emit(run_id, "skeptic", "started", "Challenging each case label with adversarial review")
    try:
        import time; t0 = time.monotonic()
        count = run_skeptic_all()
        ms = int((time.monotonic() - t0) * 1000)
        _emit(run_id, "skeptic", "finished",
              f"Reviewed {count} cases; flagged those needing human attention",
              counters={"reviewed": count}, duration_ms=ms)
        _audit(None, run_id, "system", "skeptic_complete", f"reviewed={count}")
        return {"stage": "ranker"}
    except Exception as exc:
        _emit(run_id, "skeptic", "failed", f"Skeptic review failed: {exc}")
        return {"errors": [f"skeptic: {exc}"], "stage": "ranker"}


# ---------------------------------------------------------------------------
# Node 5: ranker
# ---------------------------------------------------------------------------

def node_ranker(state: CaseState) -> dict:
    from ..comparison.rank import rank_all
    run_id = state.get("run_id") or ""
    _emit(run_id, "ranker", "started", "Scoring and prioritising cases for review")
    try:
        import time; t0 = time.monotonic()
        count = rank_all()
        ms = int((time.monotonic() - t0) * 1000)
        _emit(run_id, "ranker", "finished",
              f"Ranked {count} cases by priority score",
              counters={"ranked": count}, duration_ms=ms)
        _audit(None, run_id, "system", "ranker_complete", f"ranked={count}")
        return {"stage": "review_gate"}
    except Exception as exc:
        _emit(run_id, "ranker", "failed", f"Ranking failed: {exc}")
        return {"errors": [f"ranker: {exc}"], "stage": "review_gate"}


# ---------------------------------------------------------------------------
# Node 6: review_gate — pauses for human decision
# ---------------------------------------------------------------------------

def node_review_gate(state: CaseState) -> dict:
    """Interrupt the graph and wait for a human decision via the API."""
    run_id = state.get("run_id") or ""
    _emit(run_id, "review_gate", "paused", "Waiting for editor to review and decide on the case")
    decision = interrupt("Waiting for human decision")
    _emit(run_id, "review_gate", "finished",
          f"Editor decision received: {decision.get('action', 'unknown') if isinstance(decision, dict) else decision}")
    return {"decision": decision, "stage": "action"}


# ---------------------------------------------------------------------------
# Node 7: action — record decision and update Case state
# ---------------------------------------------------------------------------

def node_action(state: CaseState) -> dict:
    run_id = state.get("run_id") or ""
    _emit(run_id, "action", "started", "Recording editor decision and updating case state")
    decision_data = state.get("decision") or {}
    case_id = decision_data.get("case_id")
    if not case_id:
        return {"errors": ["action: no case_id in decision"], "stage": "done"}

    action = decision_data.get("action", "no_action")
    reason = decision_data.get("reason", "")
    decided_by = decision_data.get("decided_by", "unknown")
    flagged_ids = decision_data.get("flagged_paper_ids", [])

    with session_scope() as s:
        case = s.get(Case, case_id)
        if case:
            case.state = "decided"

        s.add(Decision(
            case_id=case_id,
            action=action,
            reason=reason,
            decided_by=decided_by,
            flagged_paper_ids_json=json.dumps(flagged_ids) if flagged_ids else None,
        ))

        if action == "flag_for_update" and flagged_ids:
            for pid in flagged_ids:
                s.add(RevisionItem(case_id=case_id, paper_id=pid, note=reason))

    _audit(case_id, run_id, "editor", "decision_recorded",
           f"action={action} decided_by={decided_by}")
    _emit(run_id, "action", "finished",
          f"Decision recorded: {action} by {decided_by}")
    return {"stage": "done"}
