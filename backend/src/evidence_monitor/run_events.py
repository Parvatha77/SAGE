"""Helpers for emitting RunEvent rows during agent/pipeline runs."""

import json
import time
from contextlib import contextmanager

from .db import session_scope
from .models import RunEvent

_seq_counters: dict[str, int] = {}


def _next_seq(run_id: str) -> int:
    _seq_counters[run_id] = _seq_counters.get(run_id, -1) + 1
    return _seq_counters[run_id]


def emit(
    run_id: str,
    node: str,
    status: str,
    message: str,
    counters: dict | None = None,
    cache_hit: bool = False,
    duration_ms: int | None = None,
) -> None:
    """Write a RunEvent row. Safe to call inside or outside a DB session."""
    with session_scope() as s:
        s.add(RunEvent(
            run_id=run_id,
            seq=_next_seq(run_id),
            node=node,
            status=status,
            message=message,
            counters_json=json.dumps(counters) if counters is not None else None,
            cache_hit=cache_hit,
            duration_ms=duration_ms,
        ))


@contextmanager
def timed_node(run_id: str, node: str, start_message: str):
    """Context manager that emits started/finished events with timing."""
    emit(run_id, node, "started", start_message)
    t0 = time.monotonic()
    result_holder: list = []
    try:
        yield result_holder
        ms = int((time.monotonic() - t0) * 1000)
        if result_holder:
            finished_msg, counters = result_holder[0] if isinstance(result_holder[0], tuple) else (result_holder[0], None)
        else:
            finished_msg, counters = f"{node} finished", None
        emit(run_id, node, "finished", finished_msg, counters=counters, duration_ms=ms)
    except Exception as exc:
        ms = int((time.monotonic() - t0) * 1000)
        emit(run_id, node, "failed", f"{node} failed: {exc}", duration_ms=ms)
        raise
