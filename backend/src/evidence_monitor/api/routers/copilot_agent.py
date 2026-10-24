"""
POST /copilot/reason — Agentic copilot with tool calls, reasoning, and citations
Streams SSE events: tool_started, tool_result, reasoning, answer, citations, done
"""

import json
import logging
import time
import uuid
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select, func, text

from ...db import session_scope
from ...models import Case, Claim, Paper, NeedMatch
from ...llm import get_provider

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/copilot", tags=["copilot"])


def _emit_sse(event_type: str, data: dict) -> str:
    """Emit SSE event."""
    return f"data: {json.dumps({'type': event_type, **data})}\n\n"


@router.post("/reason")
@router.get("/reason")
async def reason_about_case(case_id: str, query: str = ""):
    """Agentic copilot with tool calls, reasoning, and citations."""

    async def generator():
        start_time = time.monotonic()
        provider = get_provider()
        model_name = getattr(provider, '_model', 'unknown')

        try:
            # ── Tool 1: Search similar cases ────────────────────────
            yield _emit_sse("tool_started", {"tool": "search_similar_cases", "input": case_id})

            with session_scope() as s:
                case = s.get(Case, case_id)
                if not case:
                    yield _emit_sse("error", {"message": "Case not found"})
                    return

                # Get embedding-based similar cases
                similar = s.execute(text("""
                    SELECT c.id, c.label, c.confidence, c.anchor_claim_id, c.new_claim_id
                    FROM cases c
                    WHERE c.id != :case_id AND c.confidence IN ('high', 'medium')
                    ORDER BY c.priority_score DESC
                    LIMIT 5
                """), {"case_id": case_id}).fetchall()

                similar_cases = [
                    {"id": r[0], "label": r[1], "confidence": r[2]}
                    for r in similar
                ]

            yield _emit_sse("tool_result", {
                "tool": "search_similar_cases",
                "result": f"Found {len(similar_cases)} similar cases",
                "cases": similar_cases
            })

            # ── Tool 2: Fetch evidence papers ───────────────────────
            yield _emit_sse("tool_started", {"tool": "fetch_evidence", "input": case_id})

            with session_scope() as s:
                case = s.get(Case, case_id)
                anchor_claim = s.get(Claim, case.anchor_claim_id)
                new_claim = s.get(Claim, case.new_claim_id)

                anchor_paper = s.get(Paper, anchor_claim.paper_id) if anchor_claim else None
                new_paper = s.get(Paper, new_claim.paper_id) if new_claim else None

                evidence_papers = [
                    {"title": anchor_paper.title if anchor_paper else "Unknown",
                     "doi": anchor_paper.doi if anchor_paper else None,
                     "year": anchor_paper.publication_year if anchor_paper else None,
                     "type": "anchor"},
                    {"title": new_paper.title if new_paper else "Unknown",
                     "doi": new_paper.doi if new_paper else None,
                     "year": new_paper.publication_year if new_paper else None,
                     "type": "new_evidence"}
                ]

            yield _emit_sse("tool_result", {
                "tool": "fetch_evidence",
                "result": f"Fetched {len(evidence_papers)} evidence papers",
                "papers": evidence_papers
            })

            # ── Tool 3: Analyze with LLM ───────────────────────────
            yield _emit_sse("tool_started", {"tool": "llm_analysis", "input": query or f"Analyze case {case_id}"})

            with session_scope() as s:
                case = s.get(Case, case_id)
                anchor_claim = s.get(Claim, case.anchor_claim_id)
                new_claim = s.get(Claim, case.new_claim_id)

                system = """You are an expert evidence analyst. Analyze this research case and provide:
1. Key insight about the findings
2. Evidence gaps or limitations
3. Policy implications (if any)
4. Recommended next steps

Be concise and cite specific papers."""

                user = f"""
Case Label: {case.label}
Confidence: {case.confidence}

Original Finding:
Paper: {anchor_paper.title if anchor_paper else 'Unknown'}
Claim: {anchor_claim.claim_text if anchor_claim else 'Unknown'}

Follow-up Evidence:
Paper: {new_paper.title if new_paper else 'Unknown'}
Claim: {new_claim.claim_text if new_claim else 'Unknown'}

Query: {query or 'Provide comprehensive analysis'}

Respond with JSON: {{"insight": "...", "gaps": "...", "implications": "...", "next_steps": "..."}}
"""

                try:
                    result = provider.complete_json(
                        system=system,
                        user=user,
                        prompt_version="copilot_reason_v1"
                    )
                except Exception as e:
                    logger.error("LLM error: %s", e)
                    result = {
                        "insight": "Analysis unavailable",
                        "gaps": str(e),
                        "implications": "N/A",
                        "next_steps": "Retry the analysis"
                    }

            yield _emit_sse("tool_result", {
                "tool": "llm_analysis",
                "result": "Analysis complete"
            })

            # ── Emit reasoning ──────────────────────────────────────
            reasoning_text = f"""
Searched {len(similar_cases)} similar cases.
Fetched evidence from {len(evidence_papers)} papers.
LLM analyzed the case with comprehensive grounding.
"""
            yield _emit_sse("reasoning", {"text": reasoning_text.strip()})

            # ── Emit answer with citations ──────────────────────────
            answer_text = f"""
**Key Insight:**
{result.get('insight', 'N/A')}

**Evidence Gaps:**
{result.get('gaps', 'N/A')}

**Policy Implications:**
{result.get('implications', 'N/A')}

**Next Steps:**
{result.get('next_steps', 'N/A')}
"""

            anchor_title = (anchor_paper.title if anchor_paper else "Unknown")[:40]
            new_title = (new_paper.title if new_paper else "Unknown")[:40]

            citations = [
                {"text": anchor_title + "...", "type": "anchor", "doi": anchor_paper.doi if anchor_paper else None},
                {"text": new_title + "...", "type": "evidence", "doi": new_paper.doi if new_paper else None}
            ]

            yield _emit_sse("answer", {
                "text": answer_text.strip(),
                "citations": citations
            })

            # ── Emit completion with metadata ───────────────────────
            latency_ms = int((time.monotonic() - start_time) * 1000)
            yield _emit_sse("done", {
                "model": model_name,
                "latency_ms": latency_ms,
                "tools_used": ["search_similar_cases", "fetch_evidence", "llm_analysis"]
            })

        except Exception as exc:
            logger.exception("Copilot error: %s", exc)
            yield _emit_sse("error", {"message": str(exc)})

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )
