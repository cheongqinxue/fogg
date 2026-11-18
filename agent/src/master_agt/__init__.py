"""Master LangGraph travel assistant and its tools."""

from master_agt.agent import build_graph, get_graph

__all__ = ["build_graph", "get_graph"]


def __getattr__(name: str):
    if name == "graph":
        return get_graph()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
