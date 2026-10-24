"""POST /runs, GET /runs/{id}, GET /runs/{id}/events, GET /runs/{id}/stream, GET /runs/{id}/summary."""

import asyncio
import datetime
import json
import threading
import uuid

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from ...db import session_scope
from ...models import AgentRun, AuditEvent, Case, Claim, Paper, RunEvent
from ...run_events import emit as _emit
from ..schemas import RunRequest, RunResponse

router = APIRouter(prefix="/runs", tags=["runs"])


def _run_pipeline(run_id: str, limit: int | None) -> None:
    """Execute the full pipeline in a background thread, emitting RunEvents."""
    from ...comparison.candidates import build_embeddings, find_candidates
    from ...comparison.compare import compare_all
    from ...comparison.classify import classify_all
    from ...comparison.skeptic import run_skeptic_all
    from ...comparison.rank import rank_all
    import time

    try:
        _emit(run_id, "discovery", "started", "Building claim embeddings")
        t0 = time.monotonic()
        build_embeddings()
        pairs = find_candidates(limit=limit)
        ms = int((time.monotonic() - t0) * 1000)
        _emit(run_id, "discovery", "finished",
              f"Found {pairs} candidate pairs", counters={"pairs": pairs}, duration_ms=ms)

        _emit(run_id, "evidence", "started", "Comparing fields and classifying pairs")
        t0 = time.monotonic()
        compare_all()
        cases_created = classify_all()
        ms = int((time.monotonic() - t0) * 1000)
        _emit(run_id, "evidence", "finished",
              f"Created {cases_created} cases", counters={"cases": cases_created}, duration_ms=ms)

        _emit(run_id, "skeptic", "started", "Running adversarial label review")
        t0 = time.monotonic()
        reviewed = run_skeptic_all()
        ms = int((time.monotonic() - t0) * 1000)
        _emit(run_id, "skeptic", "finished",
              f"Reviewed {reviewed} cases", counters={"reviewed": reviewed}, duration_ms=ms)

        _emit(run_id, "ranker", "started", "Scoring and ranking cases by priority")
        t0 = time.monotonic()
        ranked = rank_all()
        ms = int((time.monotonic() - t0) * 1000)
        _emit(run_id, "ranker", "finished",
              f"Ranked {ranked} cases", counters={"ranked": ranked}, duration_ms=ms)

        with session_scope() as s:
            run = s.get(AgentRun, run_id)
            if run:
                run.status = "done"
                run.cases_created = cases_created
                run.finished_at = datetime.datetime.now(datetime.UTC)
            s.add(AuditEvent(run_id=run_id, actor="system", event="pipeline_complete",
                             detail=f"cases_created={cases_created}"))
    except Exception as exc:
        _emit(run_id, "discovery", "failed", f"Pipeline error: {exc}")
        with session_scope() as s:
            run = s.get(AgentRun, run_id)
            if run:
                run.status = "error"
                run.error = str(exc)
                run.finished_at = datetime.datetime.now(datetime.UTC)


@router.post("", response_model=RunResponse)
def start_run(body: RunRequest):
    run_id = str(uuid.uuid4())
    with session_scope() as s:
        s.add(AgentRun(id=run_id, limit=body.limit))
    threading.Thread(target=_run_pipeline, args=(run_id, body.limit), daemon=True).start()
    return RunResponse(run_id=run_id, status="running")


@router.get("/{run_id}")
def get_run(run_id: str):
    with session_scope() as s:
        run = s.get(AgentRun, run_id)
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")
        return {
            "run_id": run.id,
            "status": run.status,
            "cases_created": run.cases_created,
            "started_at": run.started_at,
            "finished_at": run.finished_at,
            "error": run.error,
        }


@router.get("/{run_id}/events")
def get_run_events(run_id: str, after: int = -1):
    """Poll for events after a given seq number."""
    with session_scope() as s:
        events = s.execute(
            select(RunEvent)
            .where(RunEvent.run_id == run_id, RunEvent.seq > after)
            .order_by(RunEvent.seq)
        ).scalars().all()
        return [
            {
                "id": e.id, "run_id": e.run_id, "seq": e.seq,
                "node": e.node, "status": e.status, "message": e.message,
                "counters": json.loads(e.counters_json) if e.counters_json else None,
                "cache_hit": e.cache_hit, "duration_ms": e.duration_ms,
                "created_at": e.created_at,
            }
            for e in events
        ]


@router.get("/{run_id}/stream")
async def stream_run_events(run_id: str):
    """Server-Sent Events stream of run events."""
    async def generator():
        last_seq = -1
        idle_ticks = 0
        while idle_ticks < 60:  # stop after 60 empty polls (~60s)
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
                        "cache_hit": e.cache_hit, "duration_ms": e.duration_ms,
                        "created_at": e.created_at.isoformat() if e.created_at else None,
                    })
                    yield f"data: {data}\n\n"
                    last_seq = e.seq
            else:
                idle_ticks += 1

            # Check if run is done
            with session_scope() as s:
                run = s.get(AgentRun, run_id)
                if run and run.status in ("done", "error"):
                    yield "data: {\"type\": \"done\"}\n\n"
                    return

            await asyncio.sleep(1)

    return StreamingResponse(generator(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/{run_id}/summary")
def get_run_summary(run_id: str):
    """Totals: papers, claims, pairs, cases, tokens, cost, seconds, cache hit rate."""
    with session_scope() as s:
        run = s.get(AgentRun, run_id)
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")

        events = s.execute(
            select(RunEvent).where(RunEvent.run_id == run_id).order_by(RunEvent.seq)
        ).scalars().all()

        # Aggregate counters from all finished events
        papers = 0
        claims = 0
        pairs = 0
        cases = 0
        total_ms = sum(e.duration_ms or 0 for e in events)
        cache_hits = sum(1 for e in events if e.cache_hit)
        total_events = len(events)

        for e in events:
            if e.counters_json:
                c = json.loads(e.counters_json)
                pairs = max(pairs, c.get("pairs", 0) or c.get("pairs_found", 0))
                cases = max(cases, c.get("cases", 0) or c.get("cases_created", 0))

        # Count directly from DB for this run's created cases
        if run.cases_created:
            cases = run.cases_created

        seconds = total_ms / 1000
        cache_rate = round(cache_hits / total_events * 100, 1) if total_events else 0.0

        return {
            "run_id": run_id,
            "status": run.status,
            "papers_scanned": papers,
            "claims_extracted": claims,
            "pairs_compared": pairs,
            "cases_created": cases,
            "seconds": round(seconds, 1),
            "cache_hit_rate": cache_rate,
            "is_replay": cache_rate > 50,
        }
