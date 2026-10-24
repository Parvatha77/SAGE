"""LangGraph graph definition for the Evidence-to-Impact Agent (UC2)."""

from langgraph.graph import StateGraph, END

from .state import UC2State
from . import nodes


def build_uc2_graph() -> StateGraph:
    g = StateGraph(UC2State)

    g.add_node("need_intake", nodes.node_need_intake)
    g.add_node("matcher", nodes.node_matcher)
    g.add_node("currency_gate", nodes.node_currency_gate)
    g.add_node("context_fit", nodes.node_context_fit)
    g.add_node("gap_check", nodes.node_gap_check)
    g.add_node("brief_writer", nodes.node_brief_writer)
    g.add_node("brief_checker", nodes.node_brief_checker)
    g.add_node("approval_gate", nodes.node_approval_gate)
    g.add_node("tracker", nodes.node_tracker)

    g.set_entry_point("need_intake")
    g.add_edge("need_intake", "matcher")
    g.add_edge("matcher", "currency_gate")
    g.add_edge("currency_gate", "context_fit")
    g.add_edge("context_fit", "gap_check")

    g.add_conditional_edges(
        "gap_check",
        lambda s: s.get("stage", "brief_writer"),
        {
            "brief_writer": "brief_writer",
            "done_no_evidence": END,
            "error": END,
        },
    )

    g.add_edge("brief_writer", "brief_checker")
    g.add_edge("brief_checker", "approval_gate")
    g.add_edge("approval_gate", "tracker")
    g.add_edge("tracker", END)

    return g
