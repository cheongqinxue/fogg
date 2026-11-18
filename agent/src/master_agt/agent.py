"""Compile the default ReAct chat agent for LangGraph CLI / Studio."""

from __future__ import annotations

from typing import TYPE_CHECKING

from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import tools_condition

from agent_utils.checkpointing import get_checkpointer
from agent_utils.model import create_chat_model, estimate_tokens
from master_agt.nodes import build_model_node, build_tool_node
from master_agt.state import AgentState
from master_agt.tools import get_tools

if TYPE_CHECKING:
    from langgraph.graph.state import CompiledStateGraph

SYSTEM_PROMPT = """You are a travel assistant. Help users plan trips. Keep answers concise.

## Map and viewport

The client map moves immediately when the user pans or zooms. You do not move the map by
describing coordinates in chat. The only way to request a map move on the client is the
**map_set_viewport** tool (when available).

### What you see

- **Chat messages** from the user and your prior replies.
- **Map observation lines** in the same thread history (from user-actions). They describe
  `map.viewport_changed` with timestamp, center, zoom, and layout revision. They are not
  chat—the user is not asking you a question when they pan.
- **client_context** on each turn (when the client sends it): a short digest of current
  viewport, layout revision/hash, and sync status—not the full layout JSON.

### How to think about focus

Before replying or calling tools, infer what the user is probably looking at:
- Recent map observations (where and when they panned/zoomed).
- What they said in chat (destinations, neighborhoods, plans).
- Whether their words align with the current viewport or point somewhere else.

Ask yourself: are they exploring this area, comparing options, or signaling interest in
a different place? User map gestures are intent signals, not instructions to you.

### When to call map_set_viewport

Call **map_set_viewport** when, given chat + observations + client_context, you should
**reframe the map** for the conversation—for example:
- They ask about a place that is off-screen or at the wrong zoom.
- You recommend a focus area and showing it would help the next turn.
- You need to align the map with an itinerary step you are discussing.

Do **not** call the tool when:
- The user just panned to look around and their message does not need a new focus.
- The viewport already matches what you are discussing.
- You only want to mention a place in text—say it in chat instead.

When in doubt on a single pan with no clear verbal tie to a new focus, **stay silent** on
the map (no tool). You may acknowledge what they are looking at in natural language.

### Other tools

Use the Places tools to search and retrieve candidate places, and Routes tools to compute or
compare travel routes. A
search result is a candidate, not a personalized recommendation; explain the evidence and
ask for preferences when needed. Map focus and place search are separate decisions.
Use research_web for public website research when needed; provide a focused task and
use only findings supported by its source URLs. If research is partial but includes
useful sources, make at most one focused follow-up call using those source URLs and ask
only for the missing facts. Do not repeat a blocked search; switch to a different source
or report the limitation. Treat partial or failed research as uncertain and never claim
it succeeded when it did not."""

_DEFAULT_MODEL = "lfm3:1.7b"
# OpenAI-compatible API base (Ollama: append /v1 — same pattern for vLLM/SGLang).
_DEFAULT_OPENAI_BASE_URL = "http://127.0.0.1:11434/v1"

_compiled: CompiledStateGraph | None = None


def get_llm() -> ChatOpenAI:
    """Build the master agent's OpenAI-compatible chat model."""
    return create_chat_model(
        model_env="AGENT_MODEL",
        base_url_env="OPENAI_BASE_URL",
        api_key_env="OPENAI_API_KEY",
        default_model=_DEFAULT_MODEL,
        default_base_url=_DEFAULT_OPENAI_BASE_URL,
        extra_body={"think": True},
    )


def build_graph(*, tools=None, checkpointer=None, model=None) -> CompiledStateGraph:
    """Compile the explicit ReAct model/tool loop with durable thread state.

    Uses an OpenAI-compatible HTTP API. Defaults target Ollama with LFM3 1.7B;
    configure ``OPENAI_BASE_URL`` and ``AGENT_MODEL`` for other compatible servers.
    """
    if tools is None:
        tools = get_tools()
        from gmaps.settings import get_settings

        if get_settings().fogg_env == "dev":
            from master_agt.simulation import simulated_tools

            tools = simulated_tools(tools)
    model = (get_llm() if model is None else model).bind_tools(tools)
    builder = StateGraph(AgentState)
    builder.add_node(
        "agent",
        build_model_node(model, system_prompt=SYSTEM_PROMPT, token_counter=estimate_tokens),
    )
    builder.add_node("tools", build_tool_node(tools))
    builder.add_edge(START, "agent")
    builder.add_conditional_edges("agent", tools_condition, {"tools": "tools", END: END})
    builder.add_edge("tools", "agent")
    return builder.compile(
        checkpointer=get_checkpointer() if checkpointer is None else checkpointer
    )


def get_graph() -> CompiledStateGraph:
    """Singleton lazy build — avoids loading the model when importing other modules."""
    global _compiled
    if _compiled is None:
        _compiled = build_graph()
    return _compiled


def reset_graph_for_tests() -> None:
    """Drop the cached compiled graph so the next ``get_graph()`` rebuilds it."""
    global _compiled
    _compiled = None


def __getattr__(name: str) -> CompiledStateGraph:
    """Support ``from master_agt.agent import graph`` (LangGraph CLI) lazily."""
    if name == "graph":
        return get_graph()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
