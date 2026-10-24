"""
POST /api/copilot/analyze — LLM-powered case analysis
POST /api/copilot/generate-brief — AI-generated policy brief
"""

import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...db import session_scope
from ...models import Case
from ...llm import get_provider

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/copilot", tags=["copilot"])


class AnalyzeRequest(BaseModel):
    case_id: str
    question: str = "Explain this case and any evidence gaps"


class AnalyzeResponse(BaseModel):
    analysis: str


class GenerateBriefRequest(BaseModel):
    need_id: str
    case_ids: list[str]
    target_audience: str = "policy makers"


class GenerateBriefResponse(BaseModel):
    brief: str
    summary: str


@router.post("/analyze", response_model=AnalyzeResponse)
def analyze_case(req: AnalyzeRequest):
    """Use LLM to analyze a case in depth."""
    with session_scope() as s:
        case = s.get(Case, req.case_id)
        if not case:
            raise HTTPException(status_code=404, detail="Case not found")

    # Build context from case
    anchor = case.anchor_claim
    new = case.new_claim
    context = f"""
Case ID: {case.id}
Label: {case.label}
Confidence: {case.confidence or 'unknown'}

ANCHOR CLAIM (original finding):
Paper: {anchor.paper_title if anchor else 'Unknown'}
Claim: {anchor.claim_text if anchor else 'Unknown'}
DOI: {anchor.paper_id if anchor else 'Unknown'}

NEW EVIDENCE (follow-up study):
Paper: {new.paper_title if new else 'Unknown'}
Claim: {new.claim_text if new else 'Unknown'}
DOI: {new.paper_id if new else 'Unknown'}

Analysis Requested: {req.question}
"""

    provider = get_provider()
    system = """You are an expert research analyst. Provide clear, evidence-grounded analysis of research claims and their implications. Be specific and cite the evidence shown."""

    try:
        result = provider.complete_json(
            system=system,
            user=context,
            prompt_version="copilot_analyze",
        )
        analysis = result.get("analysis", "Unable to generate analysis")
    except Exception as e:
        logger.error("LLM error: %s", e)
        analysis = f"Analysis unavailable: {str(e)}"

    return AnalyzeResponse(analysis=analysis)


@router.post("/generate-brief", response_model=GenerateBriefResponse)
def generate_brief(req: GenerateBriefRequest):
    """Generate an LLM-powered policy brief from cases."""
    with session_scope() as s:
        cases = []
        for cid in req.case_ids:
            c = s.get(Case, cid)
            if c:
                cases.append(c)

        if not cases:
            raise HTTPException(status_code=400, detail="No valid cases provided")

    # Build evidence summary
    evidence_text = "\n".join([
        f"- {c.anchor_claim.paper_title if c.anchor_claim else 'Study'}: {c.anchor_claim.claim_text if c.anchor_claim else ''}"
        for c in cases[:5]
    ])

    context = f"""
Create a clear, compelling policy brief for {req.target_audience}.

Key evidence:
{evidence_text}

Brief should:
1. Open with the core finding (2 sentences)
2. Explain why it matters for policy
3. Note any limitations or caveats
4. End with a clear recommendation

Keep it to 200 words max, evidence-grounded, no jargon.
"""

    provider = get_provider()
    system = """You are a policy research communicator. Write clear, evidence-grounded briefs that translate research into actionable insights for policymakers. Be specific, cite evidence, acknowledge limitations."""

    try:
        result = provider.complete_json(
            system=system,
            user=context,
            prompt_version="copilot_brief",
        )
        brief = result.get("brief", "Brief generation failed")
        summary = result.get("summary", brief[:100])
    except Exception as e:
        logger.error("LLM error: %s", e)
        brief = f"Brief generation unavailable: {str(e)}"
        summary = brief[:100]

    return GenerateBriefResponse(brief=brief, summary=summary)
