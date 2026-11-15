"""LangGraph travel assistant — graph + tools (product-neutral package name)."""

from graph.agent import build_graph, get_graph

__all__ = ["build_graph", "get_graph"]


def __getattr__(name: str):
    if name == "graph":
        return get_graph()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
