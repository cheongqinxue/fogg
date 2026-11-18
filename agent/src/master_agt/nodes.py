"""Master agent node builders backed by shared LangGraph helpers."""

from __future__ import annotations

from typing import Any

from langchain_core.messages import trim_messages

from agent_utils.langgraph import (
    build_model_node as _build_model_node,
    build_tool_node as _build_tool_node,
)
from master_agt.tools import get_tools

# Leave space in the default 32k Ollama context for tool schemas and output.
DEFAULT_MAX_INPUT_TOKENS = 20_000


def build_model_node(
    model: Any,
    *,
    system_prompt: str,
    token_counter: Any,
):
    """Build the master model node with its configured context budget."""
    return _build_model_node(
        model,
        system_prompt=system_prompt,
        token_counter=token_counter,
        max_input_tokens_env="AGENT_MAX_INPUT_TOKENS",
        default_max_input_tokens=DEFAULT_MAX_INPUT_TOKENS,
        trim_messages_fn=trim_messages,
    )


def build_tool_node(tools=None):
    """Create the master tool executor with shared execution feedback."""
    return _build_tool_node(get_tools() if tools is None else tools)


__all__ = ["build_model_node", "build_tool_node"]
