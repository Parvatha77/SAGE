"""LangGraph node functions for the Evidence-to-Impact Agent (UC2)."""

import json
import logging
import re
from sqlalchemy import select

from ..db import session_scope
from ..models import (
    AuditEvent, Brief, BriefCheck, Case, Claim, ClaimEmbedding,
    ContextFit, CoverageGap, CurrencyCheck, IntegrityNotice,
    Need, NeedMatch, Outcome, Paper,
)
from ..run_events import emit as _emit
from .state import UC2State

logger = logging.getLogger(__name__)

OVERCLAIM_WORDS = re.compile(
    r"\b(proves?|guarantees?|will reduce|will increase|causes?)\b", re.IGNORECASE
)


# ---------------------------------------------------------------------------
# 1. need_intake
# ---------------------------------------------------------------------------

def node_need_intake(state: UC2State) -> dict:
    need_id = state["need_id"]
    run_id = state.get("run_id") or need_id
    _emit(run_id, "need_intake", "started", "Loading policy need from database")
    with session_scope() as s:
        need = s.get(Need, need_id)
        if not need:
            _emit(run_id, "need_intake", "failed", f"Need {need_id} not found")
            return {"errors": [f"Need {need_id} not found"], "stage": "error"}
        need.state = "running"
        s.add(AuditEvent(need_id=need_id, actor="system", event="uc2_started",
                         detail=f"need={need.title[:60]}"))
        title = need.title
    _emit(run_id, "need_intake", "finished", f"Loaded need: {title[:60]}")
    return {"stage": "matcher", "errors": []}


# ---------------------------------------------------------------------------
# 2. matcher
# ---------------------------------------------------------------------------

def node_matcher(state: UC2State) -> dict:
    import time
    from ..comparison.candidates import _cosine  # reuse
    from ..llm import get_provider
    from ..extraction.prompts import PROMPT_VERSION

    need_id = state["need_id"]
    run_id = state.get("run_id") or need_id
    errors = list(state.get("errors", []))
    _emit(run_id, "matcher", "started", "Searching corpus for relevant claims")

    with session_scope() as s:
        need = s.get(Need, need_id)
        if not need:
            return {"errors": errors + ["Need missing in matcher"], "stage": "error"}

        keywords = json.loads(need.topic_keywords_json)
        query_text = need.need_text + " " + " ".join(keywords)

        # Embed query
        try:
            from sentence_transformers import SentenceTransformer
            model = SentenceTransformer("all-MiniLM-L6-v2")
            q_vec = model.encode([query_text])[0].tolist()
        except Exception as exc:
            errors.append(f"Embedding failed: {exc}")
            return {"errors": errors, "stage": "error"}

        # Load all claim embeddings
        rows = s.execute(select(ClaimEmbedding)).scalars().all()
        if not rows:
            s.add(CoverageGap(need_id=need_id, reason="No claim embeddings in corpus",
                              idea_text=None, status="open"))
            s.add(AuditEvent(need_id=need_id, actor="system", event="coverage_gap",
                             detail="No embeddings"))
            return {"matches": [], "stage": "gap_detected", "errors": errors}

        scored = []
        for row in rows:
            try:
                c_vec = json.loads(row.embedding_json)
                sim = float(_cosine(q_vec, c_vec))
                scored.append((sim, row.claim_id))
            except Exception:
                continue

        scored.sort(reverse=True)
        top = scored[:8]

    # LLM relevance check outside session
    provider = get_provider()
    kept = []
    with session_scope() as s:
        need = s.get(Need, need_id)
        keywords = json.loads(need.topic_keywords_json)
        for sim, claim_id in top:
            claim = s.get(Claim, claim_id)
            if not claim:
                continue
            system = (
                "You assess whether a research claim is relevant to a policy need. "
                "Output JSON: {\"relevance\": \"yes\" | \"partly\" | \"no\", \"reason\": \"one sentence\"}"
            )
            user = (
                f"POLICY NEED: {need.need_text}\n"
                f"KEYWORDS: {', '.join(keywords)}\n"
                f"CLAIM: {claim.claim_text}\n"
                f"SOURCE: \"{claim.source_sentence}\""
            )
            try:
                raw = provider.complete_json(system=system, user=user,
                                             prompt_version=f"uc2-match-{PROMPT_VERSION}")
                relevance = raw.get("relevance", "no")
                reason = raw.get("reason", "")
            except Exception as exc:
                logger.warning("LLM relevance check failed: %s", exc)
                relevance, reason = "no", str(exc)

            if relevance in ("yes", "partly"):
                fit_score = round(sim * 0.6 + (0.4 if relevance == "yes" else 0.2), 4)
                nm = NeedMatch(need_id=need_id, claim_id=claim_id,
                               paper_id=claim.paper_id, fit_score=fit_score,
                               fit_reason=reason, included=True)
                s.add(nm)
                s.flush()
                kept.append(nm.id)

    _emit(run_id, "matcher", "finished",
          f"Found {len(kept)} relevant claims from corpus",
          counters={"matches": len(kept)})
    return {"matches": kept, "stage": "currency_gate", "errors": errors}


# ---------------------------------------------------------------------------
# 3. currency_gate  (no LLM)
# ---------------------------------------------------------------------------

def node_currency_gate(state: UC2State) -> dict:
    need_id = state["need_id"]
    run_id = state.get("run_id") or need_id
    errors = list(state.get("errors", []))
    _emit(run_id, "currency_gate", "started", "Checking currency status of matched evidence")

    with session_scope() as s:
        matches = s.execute(
            select(NeedMatch).where(NeedMatch.need_id == need_id)
        ).scalars().all()

        for nm in matches:
            paper_id = nm.paper_id
            status = "current"
            note = None
            source_case_id = None

            # Retraction check
            notice = s.execute(
                select(IntegrityNotice).where(IntegrityNotice.paper_id == paper_id)
            ).scalars().first()
            if notice:
                status = "retracted"
                note = f"Integrity notice: {notice.kind} ({notice.source})"
                nm.included = False

            if status == "current":
                # Case-based currency check
                cases = s.execute(
                    select(Case).where(Case.anchor_claim_id == nm.claim_id)
                ).scalars().all()
                for case in cases:
                    if case.label == "possible_reproducibility_concern" and (
                        case.needs_human_attention or case.state != "decided"
                    ):
                        status = "challenged"
                        note = f"Reproducibility concern case {case.id[:8]}"
                        source_case_id = case.id
                        nm.included = False
                        break
                    if case.label == "differs_in_context":
                        status = "current_with_note"
                        note = f"Context differs (case {case.id[:8]}): {case.rationale or ''}"
                        source_case_id = case.id
                        # included stays True
                    if (case.state == "ready_for_review"
                            and case.priority_score
                            and case.priority_score >= 70.0
                            and status == "current"):
                        status = "under_review"
                        note = f"High-priority case {case.id[:8]} is unresolved"
                        source_case_id = case.id
                        nm.included = False

            s.add(CurrencyCheck(need_match_id=nm.id, status=status,
                                source_case_id=source_case_id, note=note))

    retracted = sum(1 for nm in matches if not nm.included)
    _emit(run_id, "currency_gate", "finished",
          f"Checked {len(matches)} matches; {retracted} excluded by currency rules",
          counters={"checked": len(matches), "excluded": retracted})
    return {"stage": "context_fit", "errors": errors}


# ---------------------------------------------------------------------------
# 4. context_fit  (no LLM — reuses field comparison logic)
# ---------------------------------------------------------------------------

def _field_sim(a: str | None, b: str | None) -> str:
    """Simple: unknown if either missing, else 'similar' or 'differs' by overlap."""
    if not a or not b:
        return "unknown"
    a_words = set(a.lower().split())
    b_words = set(b.lower().split())
    if not a_words or not b_words:
        return "unknown"
    overlap = len(a_words & b_words) / max(len(a_words), len(b_words))
    return "similar" if overlap >= 0.3 else "differs"


def node_context_fit(state: UC2State) -> dict:
    need_id = state["need_id"]
    run_id = state.get("run_id") or need_id
    errors = list(state.get("errors", []))
    _emit(run_id, "context_fit", "started", "Assessing context fit for policy jurisdiction and population")

    with session_scope() as s:
        need = s.get(Need, need_id)
        matches = s.execute(
            select(NeedMatch).where(NeedMatch.need_id == need_id)
        ).scalars().all()

        for nm in matches:
            claim = s.get(Claim, nm.claim_id)
            if not claim:
                continue

            pop_sim = _field_sim(claim.population, need.population_of_interest)
            set_sim = _field_sim(claim.country_or_setting, need.setting_of_interest)

            notes = {"population": pop_sim, "setting": set_sim}

            if pop_sim == "unknown" or set_sim == "unknown":
                level = "unknown"
            elif pop_sim == "similar" and set_sim == "similar":
                level = "good"
            elif pop_sim == "similar" or set_sim == "similar":
                level = "partial"
            else:
                level = "poor"

            s.add(ContextFit(need_match_id=nm.id, level=level,
                             field_notes_json=json.dumps(notes)))

    good = sum(1 for nm in matches if True)  # counted via context_fits added
    _emit(run_id, "context_fit", "finished",
          f"Assessed context fit for {len(matches)} matches")
    return {"stage": "gap_check", "errors": errors}


# ---------------------------------------------------------------------------
# 5. gap detection
# ---------------------------------------------------------------------------

def node_gap_check(state: UC2State) -> dict:
    from ..llm import get_provider
    from ..extraction.prompts import PROMPT_VERSION

    need_id = state["need_id"]
    run_id = state.get("run_id") or need_id
    errors = list(state.get("errors", []))
    _emit(run_id, "gap_check", "started", "Checking whether evidence is sufficient or a gap exists")

    with session_scope() as s:
        need = s.get(Need, need_id)
        usable = s.execute(
            select(NeedMatch).where(NeedMatch.need_id == need_id,
                                    NeedMatch.included == True)
        ).scalars().all()

        if len(usable) >= 2 and (not usable or max(m.fit_score for m in usable) >= 0.3):
            return {"stage": "brief_writer", "errors": errors}

        # Draft commissioning idea via LLM
        provider = get_provider()
        system = (
            "You draft a brief commissioning idea for a research gap. "
            "Output JSON: {\"idea\": \"2-3 sentence commissioning idea\"}"
        )
        user = (
            f"POLICY NEED: {need.need_text}\n"
            f"KEYWORDS: {', '.join(json.loads(need.topic_keywords_json))}\n"
            f"USABLE MATCHES FOUND: {len(usable)}\n"
            "Draft a commissioning idea to fill this gap."
        )
        try:
            raw = provider.complete_json(system=system, user=user,
                                         prompt_version=f"uc2-gap-{PROMPT_VERSION}")
            idea_text = raw.get("idea", "")
        except Exception as exc:
            logger.warning("Gap LLM failed: %s", exc)
            idea_text = None

        reason = (
            f"Only {len(usable)} usable match(es) found "
            f"(need at least 2 with fit_score ≥ 0.3)."
        )
        gap = CoverageGap(need_id=need_id, reason=reason,
                          idea_text=idea_text, status="open")
        s.add(gap)
        s.flush()
        gap_id = gap.id
        s.add(AuditEvent(need_id=need_id, actor="system", event="coverage_gap",
                         detail=reason[:120]))

    if len(usable) == 0:
        _emit(run_id, "gap_check", "finished",
              "No usable evidence found; coverage gap recorded",
              counters={"usable_matches": 0})
        return {"gap_id": gap_id, "stage": "done_no_evidence", "errors": errors}

    _emit(run_id, "gap_check", "finished",
          f"Gap recorded; {len(usable)} usable matches still available for brief",
          counters={"usable_matches": len(usable)})
    return {"gap_id": gap_id, "stage": "brief_writer", "errors": errors}


# ---------------------------------------------------------------------------
# 6. brief_writer
# ---------------------------------------------------------------------------

def node_brief_writer(state: UC2State) -> dict:
    from ..llm import get_provider
    from ..extraction.prompts import PROMPT_VERSION

    need_id = state["need_id"]
    run_id = state.get("run_id") or need_id
    errors = list(state.get("errors", []))
    _emit(run_id, "brief_writer", "started", "Drafting plain-language evidence brief")

    with session_scope() as s:
        need = s.get(Need, need_id)
        matches = s.execute(
            select(NeedMatch).where(NeedMatch.need_id == need_id,
                                    NeedMatch.included == True)
        ).scalars().all()

        if not matches:
            return {"errors": errors + ["No included matches for brief"], "stage": "error"}

        claim_blocks = []
        supplied_ids = []
        for nm in matches:
            claim = s.get(Claim, nm.claim_id)
            paper = s.get(Paper, nm.paper_id)
            cc = s.execute(
                select(CurrencyCheck).where(CurrencyCheck.need_match_id == nm.id)
            ).scalars().first()
            cf = s.execute(
                select(ContextFit).where(ContextFit.need_match_id == nm.id)
            ).scalars().first()

            currency_note = f"[currency: {cc.status}" + (f" — {cc.note}" if cc and cc.note else "") + "]" if cc else ""
            context_note = f"[context fit: {cf.level}]" if cf else ""

            block = (
                f"CLAIM_ID: {claim.id}\n"
                f"PAPER: {paper.title[:80] if paper else 'unknown'} "
                f"({paper.publication_year if paper else 'unknown'})\n"
                f"SOURCE: \"{claim.source_sentence}\"\n"
                f"CLAIM: {claim.claim_text}\n"
                f"{currency_note} {context_note}"
            )
            claim_blocks.append(block)
            supplied_ids.append(claim.id)

        need_text = need.need_text
        audience = need.audience

    provider = get_provider()
    system = (
        "You write a plain-language evidence brief for a policy audience. "
        "Target reading age: 12 years. Maximum 220 words. "
        "Required sections: 'What the research shows' and 'Limits to keep in mind'. "
        "Cite each finding by its CLAIM_ID in brackets. "
        "Use ONLY the claims provided — do not add outside facts. "
        "State the currency date or note if evidence is under review. "
        "Output JSON: {\"text\": \"<brief text>\", \"claim_ids\": [\"id1\", ...]}"
    )
    user = (
        f"POLICY NEED: {need_text}\n"
        f"AUDIENCE: {audience}\n\n"
        "EVIDENCE:\n" + "\n\n".join(claim_blocks)
    )

    try:
        raw = provider.complete_json(system=system, user=user,
                                     prompt_version=f"uc2-brief-{PROMPT_VERSION}")
        brief_text = raw.get("text", "")
        used_ids = raw.get("claim_ids", [])
    except Exception as exc:
        errors.append(f"Brief LLM failed: {exc}")
        return {"errors": errors, "stage": "error"}

    # Hard reject any claim id not in supplied set
    invalid = [cid for cid in used_ids if cid not in supplied_ids]
    if invalid:
        errors.append(f"Brief cited unsupplied claim ids: {invalid}")
        return {"errors": errors, "stage": "error"}

    with session_scope() as s:
        need = s.get(Need, need_id)
        existing = s.execute(
            select(Brief).where(Brief.need_id == need_id)
        ).scalars().all()
        version = len(existing) + 1
        brief = Brief(need_id=need_id, version=version, text=brief_text,
                      claim_ids_json=json.dumps(used_ids), status="draft")
        s.add(brief)
        s.flush()
        brief_id = brief.id
        s.add(AuditEvent(need_id=need_id, actor="system", event="brief_drafted",
                         detail=f"version={version} words={len(brief_text.split())}"))

    _emit(run_id, "brief_writer", "finished",
          f"Brief drafted (version {version}, {len(brief_text.split())} words)",
          counters={"words": len(brief_text.split()), "claims_cited": len(used_ids)})
    return {"brief_id": brief_id, "brief_text": brief_text,
            "stage": "brief_checker", "errors": errors}


# ---------------------------------------------------------------------------
# 7. brief_checker  (no LLM)
# ---------------------------------------------------------------------------

def _run_checks(brief_id: str, need_id: str) -> tuple[list[dict], float]:
    """Run all deterministic checks; return (check_rows, readiness_score 0-100)."""
    with session_scope() as s:
        brief = s.get(Brief, brief_id)
        text = brief.text
        used_ids = set(json.loads(brief.claim_ids_json))

        matches = s.execute(
            select(NeedMatch).where(NeedMatch.need_id == need_id,
                                    NeedMatch.included == True)
        ).scalars().all()
        allowed_ids = {nm.claim_id for nm in matches}
        excluded_ids = set()
        all_nm = s.execute(
            select(NeedMatch).where(NeedMatch.need_id == need_id,
                                    NeedMatch.included == False)
        ).scalars().all()
        excluded_ids = {nm.claim_id for nm in all_nm}

        checks = []

        # 1. No excluded claim used
        bad = used_ids & excluded_ids
        checks.append({"name": "no_excluded_claim",
                        "passed": len(bad) == 0,
                        "detail": f"Excluded claim(s) used: {bad}" if bad else None})

        # 2. Limits section present
        has_limits = bool(re.search(r"limits?\s+to\s+keep", text, re.IGNORECASE)
                          or re.search(r"##?\s*limits", text, re.IGNORECASE))
        checks.append({"name": "limits_section_present",
                        "passed": has_limits,
                        "detail": None if has_limits else "Missing 'Limits to keep in mind' section"})

        # 3. No overclaiming words (unless design supports it — simple heuristic)
        oc = OVERCLAIM_WORDS.findall(text)
        checks.append({"name": "no_overclaiming",
                        "passed": len(oc) == 0,
                        "detail": f"Overclaiming words: {oc}" if oc else None})

        # 4. Length under 220 words
        word_count = len(text.split())
        checks.append({"name": "length_under_220",
                        "passed": word_count <= 220,
                        "detail": f"{word_count} words" if word_count > 220 else None})

        # 5. Every used claim id has a paper citation in text (claim id appears)
        missing_cites = [cid for cid in used_ids if cid not in text]
        checks.append({"name": "all_claims_cited_in_text",
                        "passed": len(missing_cites) == 0,
                        "detail": f"IDs not in text: {missing_cites}" if missing_cites else None})

        # 6. Currency date or note stated
        has_currency = bool(re.search(r"\b(20\d\d|under review|current|currency)\b", text, re.IGNORECASE))
        checks.append({"name": "currency_noted",
                        "passed": has_currency,
                        "detail": None if has_currency else "No currency date or note found in brief"})

        # Readiness score: 50% checks, 50% avg fit
        checks_score = sum(1 for c in checks if c["passed"]) / len(checks) * 50
        fit_scores = []
        for nm in matches:
            if nm.claim_id in used_ids:
                fit_scores.append(nm.fit_score)
        fit_avg = (sum(fit_scores) / len(fit_scores)) if fit_scores else 0.0
        readiness = round(checks_score + fit_avg * 50, 1)

        return checks, readiness


def node_brief_checker(state: UC2State) -> dict:
    need_id = state["need_id"]
    run_id = state.get("run_id") or need_id
    brief_id = state.get("brief_id")
    errors = list(state.get("errors", []))
    _emit(run_id, "brief_checker", "started", "Running quality checks on the evidence brief")

    if not brief_id:
        return {"errors": errors + ["No brief_id in state"], "stage": "error"}

    checks, readiness = _run_checks(brief_id, need_id)

    with session_scope() as s:
        for c in checks:
            s.add(BriefCheck(brief_id=brief_id, check_name=c["name"],
                             passed=c["passed"], detail=c["detail"]))

    passed = sum(1 for c in checks if c["passed"])
    _emit(run_id, "brief_checker", "finished",
          f"Brief quality checks: {passed}/{len(checks)} passed, readiness score {readiness}",
          counters={"checks_passed": passed, "readiness": readiness})
    return {"readiness_score": readiness, "stage": "approval_gate", "errors": errors}


# ---------------------------------------------------------------------------
# 8. approval_gate  (interrupt)
# ---------------------------------------------------------------------------

def node_approval_gate(state: UC2State) -> dict:
    from langgraph.types import interrupt
    run_id = state.get("run_id") or state.get("need_id") or ""
    _emit(run_id, "approval_gate", "paused", "Waiting for editor to approve or reject the brief")
    decision = interrupt("Awaiting human approval or rejection")
    _emit(run_id, "approval_gate", "finished",
          f"Editor decision received: {decision.get('action', 'unknown') if isinstance(decision, dict) else decision}")
    return {"decision": decision, "stage": "tracker"}


# ---------------------------------------------------------------------------
# 9. tracker
# ---------------------------------------------------------------------------

def node_tracker(state: UC2State) -> dict:
    need_id = state["need_id"]
    run_id = state.get("run_id") or need_id
    brief_id = state.get("brief_id")
    decision = state.get("decision") or {}
    errors = list(state.get("errors", []))
    _emit(run_id, "tracker", "started", "Recording decision and updating need state")

    action = decision.get("action", "approved")

    with session_scope() as s:
        need = s.get(Need, need_id)
        if not need:
            return {"errors": errors + ["Need missing in tracker"], "stage": "error"}

        if action == "approved":
            approver = decision.get("approver", "unknown")
            if not approver or approver == "unknown":
                errors.append("Approval requires approver name")
                return {"errors": errors, "stage": "error"}
            need.state = "approved"
            if brief_id:
                import datetime
                brief = s.get(Brief, brief_id)
                if brief:
                    brief.status = "approved"
                    brief.approved_by = approver
                    brief.approved_at = datetime.datetime.now(datetime.UTC)
            s.add(AuditEvent(need_id=need_id, actor=approver, event="brief_approved",
                             detail=decision.get("reason", "")))
        else:
            reason = decision.get("reason", "")
            if not reason:
                errors.append("Rejection requires a reason")
                return {"errors": errors, "stage": "error"}
            need.state = "new"
            if brief_id:
                brief = s.get(Brief, brief_id)
                if brief:
                    brief.status = "draft"
            s.add(AuditEvent(need_id=need_id, actor=decision.get("approver", "editor"),
                             event="brief_rejected", detail=reason))

    _emit(run_id, "tracker", "finished",
          f"Need state updated to '{decision.get('action', 'approved')}' and recorded")
    return {"stage": "done", "errors": errors}
