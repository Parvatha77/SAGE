"""LangGraph graph definition with SQLite checkpointer."""

import os
from pathlib import Path

from langgraph.graph import END, StateGraph
from langgraph.checkpoint.sqlite import SqliteSaver

from .state import CaseState
from .nodes import (
    node_discovery,
    node_evidence,
    node_integrity,
    node_skeptic,
    node_ranker,
    node_review_gate,
    node_action,
)

_CHECKPOINT_DB = os.environ.get("CHECKPOINT_DB", str(Path("evidence_checkpoints.db")))


def get_checkpointer() -> SqliteSaver:
    """Return a SqliteSaver. Swap to AsyncPostgresSaver here when moving to Postgres."""
    return SqliteSaver.from_conn_string(_CHECKPOINT_DB)


def build_graph():
    g = StateGraph(CaseState)

    g.add_node("discovery", node_discovery)
    g.add_node("evidence", node_evidence)
    g.add_node("integrity", node_integrity)
    g.add_node("skeptic", node_skeptic)
    g.add_node("ranker", node_ranker)
    g.add_node("review_gate", node_review_gate)
    g.add_node("action", node_action)

    g.set_entry_point("discovery")
    g.add_edge("discovery", "evidence")
    g.add_edge("evidence", "integrity")
    g.add_edge("integrity", "skeptic")
    g.add_edge("skeptic", "ranker")
    g.add_edge("ranker", "review_gate")
    g.add_edge("review_gate", "action")
    g.add_edge("action", END)

    return g
