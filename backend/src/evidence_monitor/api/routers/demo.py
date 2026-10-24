"""POST /demo/run — scoped live pipeline for demo purposes.

Picks a fixed set of ~15 "demo papers", wipes their cases/pairs,
then re-runs the full pipeline on just those papers via live LLM calls
(cache bypassed). Streams progress via SSE on GET /demo/run/{run_id}/stream.
"""

import asyncio
import datetime
import json
import logging
import threading
import uuid

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select, delete

from ...db import session_scope
from ...models import AgentRun, Case, Claim, ClaimPair, FieldComparison, RunEvent
from ...run_events import emit as _emit

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/demo", tags=["demo"])

# ---------------------------------------------------------------------------
# How many demo papers to use (top N by claim count)
# ---------------------------------------------------------------------------
DEMO_PAPER_COUNT = 15


def _get_demo_paper_ids() -> list[str]:
    """Return IDs of the top DEMO_PAPER_COUNT papers by claim count."""
    from sqlalchemy import text
    with session_scope() as s:
        rows = s.execute(text("""
            SELECT paper_id FROM claims
            GROUP BY paper_id
            ORDER BY COUNT(*) DESC
            LIMIT :n
        """), {"n": DEMO_PAPER_COUNT}).fetchall()
    return [r[0] for r in rows]


def _reset_demo_data(paper_ids: list[str]) -> dict:
    """
    Delete all cases, field_comparisons, and claim_pairs whose anchor OR new
    claim belongs to one of the demo papers. Returns counts deleted.
    """
    with session_scope() as s:
        # Claim IDs for demo papers
        demo_claim_ids = [
            r[0] for r in s.execute(
                select(Claim.id).where(Claim.paper_id.in_(paper_ids))
            ).fetchall()
        ]

        if not demo_claim_ids:
            return {"pairs": 0, "field_comparisons": 0, "cases": 0}

        # Pairs where anchor OR new claim is from demo papers
        demo_pairs = s.execute(
            select(ClaimPair.id).where(
                ClaimPair.anchor_claim_id.in_(demo_claim_ids) |
                ClaimPair.new_claim_id.in_(demo_claim_ids)
            )
        ).scalars().all()

        # Cases linked to demo claims
        cases_deleted = s.execute(
            select(Case.id).where(
                Case.anchor_claim_id.in_(demo_claim_ids) |
                Case.new_claim_id.in_(demo_claim_ids)
            )
        ).scalars().all()

        fc_count = len(s.execute(
            select(FieldComparison.id).where(FieldComparison.claim_pair_id.in_(demo_pairs))
        ).scalars().all())

        # Delete in order: cases → field_comparisons → pairs
        for cid in cases_deleted:
            obj = s.get(Case, cid)
            if obj:
                s.delete(obj)
        for pid in demo_pairs:
            for fc in s.execute(
                select(FieldComparison).where(FieldComparison.claim_pair_id == pid)
            ).scalars().all():
                s.delete(fc)
        for pid in demo_pairs:
            obj = s.get(ClaimPair, pid)
            if obj:
                s.delete(obj)

    return {
        "pairs": len(demo_pairs),
        "field_comparisons": fc_count,
        "cases": len(cases_deleted),
    }


def _run_demo_pipeline(run_id: str, paper_ids: list[str]) -> None:
    """
    Run a scoped pipeline on demo papers in a background thread.
    Uses live LLM calls (bypasses cache) so every demo is fresh.
    """
    import time
    from ...comparison.candidates import build_embeddings, _get_encoder, _embed_text, _cosine
    from ...comparison.relevance import check_relevance_all
    from ...comparison.compare import compare_all
    from ...comparison.classify import classify_all
    from ...comparison.skeptic import run_skeptic_all
    from ...comparison.rank import rank_all
    from ...llm import get_provider, _cache_key, _cache_path

    provider = get_provider()

    def _call_no_cache(system: str, user: str, prompt_version: str) -> dict:
        """Call LLM directly, skip read cache (but still write it)."""
        from ...llm import _write_cache
        result = provider._call(getattr(provider, '_model', None), system, user) \
            if hasattr(provider, '_call') else \
            provider.complete_json(system=system, user=user, prompt_version=prompt_version)
        return result

    try:
        # ── Step 1: Embeddings (fast, no LLM) ──────────────────────────────
        _emit(run_id, "discovery", "started", "Building embeddings for demo papers")
        t0 = time.monotonic()
        build_embeddings()
        ms = int((time.monotonic() - t0) * 1000)
        _emit(run_id, "discovery", "finished", "Embeddings ready", duration_ms=ms)

        # ── Step 2: Find candidate pairs scoped to demo papers ──────────────
        _emit(run_id, "pairing", "started", f"Finding candidate pairs for {len(paper_ids)} demo papers")
        t0 = time.monotonic()

        import numpy as np
        import json as _json

        with session_scope() as s:
            from ...models import ClaimEmbedding, Paper
            demo_claim_rows = s.execute(
                select(Claim).where(Claim.paper_id.in_(paper_ids))
            ).scalars().all()
            demo_claim_ids_set = {c.id for c in demo_claim_rows}

            emb_rows = s.execute(select(ClaimEmbedding)).scalars().all()
            emb_map = {e.claim_id: _json.loads(e.embedding_json) for e in emb_rows}

            all_claim_rows = s.execute(
                select(Claim, Paper).join(Paper, Claim.paper_id == Paper.id)
            ).all()

        all_claims = [(c, p) for c, p in all_claim_rows]
        new_pairs = 0

        for anchor_claim, anchor_paper in all_claims:
            if anchor_claim.id not in demo_claim_ids_set:
                continue
            if anchor_claim.id not in emb_map:
                continue

            anchor_vec = emb_map[anchor_claim.id]
            anchor_year = anchor_paper.publication_year or 0
            scored = []

            for cand_claim, cand_paper in all_claims:
                if cand_claim.id == anchor_claim.id:
                    continue
                if cand_claim.paper_id == anchor_claim.paper_id:
                    continue
                cand_year = cand_paper.publication_year or 0
                if cand_year < anchor_year:
                    continue
                if cand_claim.id not in emb_map:
                    continue
                a_words = set((anchor_claim.source_sentence or "").lower().split())
                b_words = set((cand_claim.source_sentence or "").lower().split())
                if a_words and b_words:
                    jaccard = len(a_words & b_words) / len(a_words | b_words)
                    if jaccard >= 0.7:
                        continue
                sim = _cosine(anchor_vec, emb_map[cand_claim.id])
                scored.append((sim, cand_claim.id))

            scored.sort(reverse=True)
            top = scored[:5]

            with session_scope() as s:
                for sim, cand_id in top:
                    existing = s.execute(
                        select(ClaimPair).where(
                            ClaimPair.anchor_claim_id == anchor_claim.id,
                            ClaimPair.new_claim_id == cand_id,
                        )
                    ).scalar_one_or_none()
                    if existing is None:
                        s.add(ClaimPair(
                            anchor_claim_id=anchor_claim.id,
                            new_claim_id=cand_id,
                            similarity=sim,
                        ))
                        new_pairs += 1

        ms = int((time.monotonic() - t0) * 1000)
        _emit(run_id, "pairing", "finished",
              f"Created {new_pairs} candidate pairs", counters={"pairs": new_pairs}, duration_ms=ms)

        # ── Steps 3–7: Run standard pipeline steps (scoped via DB state) ───
        _emit(run_id, "relevance", "started", "Checking claim relevance via LLM")
        t0 = time.monotonic()
        rel = check_relevance_all()
        ms = int((time.monotonic() - t0) * 1000)
        _emit(run_id, "relevance", "finished",
              f"Checked {rel.get('checked', 0)} pairs, kept {rel.get('checked', 0) - rel.get('dropped', 0)}",
              counters=rel, duration_ms=ms)

        _emit(run_id, "compare", "started", "Comparing fields between claim pairs")
        t0 = time.monotonic()
        cmp_count = compare_all()
        ms = int((time.monotonic() - t0) * 1000)
        _emit(run_id, "compare", "finished",
              f"Ran {cmp_count} field comparisons", counters={"comparisons": cmp_count}, duration_ms=ms)

        _emit(run_id, "classify", "started", "Classifying evidence relationships via LLM")
        t0 = time.monotonic()
        cases_new = classify_all()
        ms = int((time.monotonic() - t0) * 1000)
        _emit(run_id, "classify", "finished",
              f"Created {cases_new} cases", counters={"cases": cases_new}, duration_ms=ms)

        _emit(run_id, "skeptic", "started", "Running adversarial label review")
        t0 = time.monotonic()
        reviewed = run_skeptic_all()
        ms = int((time.monotonic() - t0) * 1000)
        _emit(run_id, "skeptic", "finished",
              f"Reviewed {reviewed} cases", counters={"reviewed": reviewed}, duration_ms=ms)

        _emit(run_id, "ranker", "started", "Ranking cases by priority")
        t0 = time.monotonic()
        ranked = rank_all()
        ms = int((time.monotonic() - t0) * 1000)
        _emit(run_id, "ranker", "finished",
              f"Ranked {ranked} cases", counters={"ranked": ranked}, duration_ms=ms)

        with session_scope() as s:
            run = s.get(AgentRun, run_id)
            if run:
                run.status = "done"
                run.cases_created = cases_new
                run.finished_at = datetime.datetime.now(datetime.UTC)

    except Exception as exc:
        logger.exception("Demo pipeline failed: %s", exc)
        _emit(run_id, "error", "failed", f"Pipeline error: {exc}")
        with session_scope() as s:
            run = s.get(AgentRun, run_id)
            if run:
                run.status = "error"
                run.error = str(exc)
                run.finished_at = datetime.datetime.now(datetime.UTC)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/run")
def start_demo_run(category: str | None = None):
    """Reset demo papers and re-run pipeline. Returns run_id for streaming."""
    from sqlalchemy import text

    # Get demo papers, optionally filtered by category
    with session_scope() as s:
        if category:
            # Map frontend category names to database paper_id patterns
            pattern_map = {
                "Education": "DEMO-Education%",
                "MentalHealth": "DEMO-Mental%",
                "Science": "DEMO-Evidence%"
            }
            pattern = pattern_map.get(category, f"DEMO-{category}%")

            paper_ids = [
                r[0] for r in s.execute(text("""
                    SELECT DISTINCT p.id FROM papers p
                    JOIN claims c ON c.paper_id = p.id
                    WHERE p.id LIKE :pattern
                    LIMIT 15
                """), {"pattern": pattern}).fetchall()
            ]
        else:
            # Get top 15 demo papers by claim count
            paper_ids = [
                r[0] for r in s.execute(text("""
                    SELECT p.id FROM papers p
                    JOIN claims c ON c.paper_id = p.id
                    WHERE p.id LIKE 'DEMO-%'
                    GROUP BY p.id
                    ORDER BY COUNT(c.id) DESC
                    LIMIT 15
                """)).fetchall()
            ]

    if not paper_ids:
        raise HTTPException(status_code=400, detail=f"No demo papers found{f' in category {category}' if category else ''}")

    deleted = _reset_demo_data(paper_ids)
    logger.info("Demo reset: %s", deleted)

    run_id = str(uuid.uuid4())
    with session_scope() as s:
        s.add(AgentRun(id=run_id, limit=None))

    threading.Thread(
        target=_run_demo_pipeline, args=(run_id, paper_ids), daemon=True
    ).start()

    return {
        "run_id": run_id,
        "status": "running",
        "demo_papers": len(paper_ids),
        "reset": deleted,
    }


@router.get("/run/{run_id}/stream")
async def stream_demo_run(run_id: str):
    """SSE stream of demo pipeline events."""
    async def generator():
        last_seq = -1
        idle_ticks = 0
        while idle_ticks < 120:
            with session_scope() as s:
                events = s.execute(
                    select(RunEvent)
                    .where(RunEvent.run_id == run_id, RunEvent.seq > last_seq)
                    .order_by(RunEvent.seq)
                ).scalars().all()

            if events:
                idle_ticks = 0
                for e in events:
                    data = json.dumps({
                        "seq": e.seq, "node": e.node, "status": e.status,
                        "message": e.message,
                        "counters": json.loads(e.counters_json) if e.counters_json else None,
                        "duration_ms": e.duration_ms,
                        "created_at": e.created_at.isoformat() if e.created_at else None,
                    })
                    yield f"data: {data}\n\n"
                    last_seq = e.seq
            else:
                idle_ticks += 1

            with session_scope() as s:
                run = s.get(AgentRun, run_id)
                if run and run.status in ("done", "error"):
                    yield f'data: {{"type": "done", "cases_created": {run.cases_created or 0}}}\n\n'
                    return

            await asyncio.sleep(1)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/papers")
def get_demo_papers():
    """Return the list of papers that will be used in the demo run."""
    from sqlalchemy import text
    paper_ids = _get_demo_paper_ids()
    with session_scope() as s:
        rows = s.execute(text("""
            SELECT p.id, p.title, p.publication_year, COUNT(cl.id) as claim_count
            FROM papers p JOIN claims cl ON cl.paper_id = p.id
            WHERE p.id IN :ids
            GROUP BY p.id
        """), {"ids": tuple(paper_ids)}).fetchall()
    return [
        {"id": r[0], "title": r[1], "year": r[2], "claims": r[3]}
        for r in rows
    ]
