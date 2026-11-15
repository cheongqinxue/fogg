"""Nodes and routing helpers for the explicit ReAct loop."""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

from langchain_core.messages import SystemMessage, trim_messages
from langchain_core.runnables import Runnable
from langgraph.prebuilt import ToolNode
from langgraph.prebuilt.tool_node import ToolInvocationError

from graph.state import AgentState
from graph.tools import get_tools

# Leave space in the default 32k Ollama context for tool schemas and output.
DEFAULT_MAX_INPUT_TOKENS = 20_000


def build_model_node(
    model: Runnable[Any, Any],
    *,
    system_prompt: str,
    token_counter: Any,
) -> Callable[[AgentState], Any]:
    """Build the model node, preserving context trimming and system prompting."""

    async def call_model(state: AgentState) -> dict[str, list[Any]]:
        messages = trim_messages(
            [SystemMessage(content=system_prompt), *state["messages"]],
            max_tokens=int(os.environ.get("AGENT_MAX_INPUT_TOKENS", DEFAULT_MAX_INPUT_TOKENS)),
            strategy="last",
            token_counter=token_counter,
            include_system=True,
            start_on="human",
        )
        response = await model.ainvoke(messages)
        return {"messages": [response]}

    return call_model


def _tool_error_message(error: Exception) -> str:
    """Return tool errors with validation-specific recovery guidance."""
    if isinstance(error, ToolInvocationError):
        return (
            f"{error.message}\nCorrect the invalid arguments and retry the tool call; "
            "do not repeat the same invalid arguments."
        )
    return (
        f"Tool execution failed ({type(error).__name__}): {error}. "
        "Use this information to explain the failure or choose another approach."
    )


def build_tool_node(tools=None):
    """Create the tool executor with model-visible execution and validation feedback."""
    return ToolNode(get_tools() if tools is None else tools, handle_tool_errors=_tool_error_message)


__all__ = ["build_model_node", "build_tool_node"]
