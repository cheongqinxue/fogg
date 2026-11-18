"""Reusable LangGraph model and tool node builders."""

from __future__ import annotations

import os
from collections.abc import Callable, Sequence
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage, trim_messages
from langchain_core.runnables import Runnable
from langchain_core.tools import BaseTool
from langgraph.prebuilt import ToolNode
from langgraph.prebuilt.tool_node import ToolInvocationError


def build_model_node(
    model: Runnable[Any, Any],
    *,
    system_prompt: str,
    token_counter: Callable[[Sequence[Any]], int],
    max_input_tokens_env: str,
    default_max_input_tokens: int,
    trim_messages_fn: Callable[..., list[Any]] = trim_messages,
    message_preparer: Callable[[list[Any], int, Callable[[Sequence[Any]], int]], list[Any]]
    | None = None,
) -> Callable[[dict[str, Any]], Any]:
    """Build an async model node with system prompting and bounded message history."""

    async def call_model(state: dict[str, Any]) -> dict[str, list[Any]]:
        system_message = SystemMessage(content=system_prompt)
        history = state["messages"]
        max_tokens = int(os.environ.get(max_input_tokens_env, default_max_input_tokens))
        if message_preparer is not None:
            messages = message_preparer([system_message, *history], max_tokens, token_counter)
        else:
            messages = trim_messages_fn(
                [system_message, *history],
                max_tokens=max_tokens,
                strategy="last",
                token_counter=token_counter,
                include_system=True,
                start_on="human",
            )

        # A long tool transcript can consume the whole budget and leave the model
        # with only its system prompt. Keep the latest user request as the anchor
        # for the active turn, then retain as much of that turn's recent context as
        # fits. This is especially important for delegated research tasks, where
        # losing the request makes the model invent an unrelated task.
        latest_human_index = next(
            (
                index
                for index in range(len(history) - 1, -1, -1)
                if isinstance(history[index], HumanMessage)
            ),
            None,
        )
        latest_human = history[latest_human_index] if latest_human_index is not None else None
        latest_human_was_trimmed = latest_human_index is not None and not any(
            message is latest_human for message in messages
        )
        if latest_human_was_trimmed:
            active_turn = history[latest_human_index:]
            remaining_tokens = max(1, max_tokens - token_counter([system_message]))
            trimmed_turn = trim_messages_fn(
                active_turn,
                max_tokens=remaining_tokens,
                strategy="last",
                token_counter=token_counter,
                include_system=False,
                start_on="human",
            )
            if not any(isinstance(message, HumanMessage) for message in trimmed_turn):
                trimmed_turn = [history[latest_human_index]]
            messages = [system_message, *trimmed_turn]

        response = await model.ainvoke(messages)
        return {"messages": [response]}

    return call_model


def tool_error_message(error: Exception) -> str:
    """Format tool failures as model-visible recovery guidance."""
    if isinstance(error, ToolInvocationError):
        return (
            f"{error.message}\nCorrect the invalid arguments and retry the tool call; "
            "do not repeat the same invalid arguments."
        )
    return (
        f"Tool execution failed ({type(error).__name__}): {error}. "
        "Use this information to explain the failure or choose another approach."
    )


def build_tool_node(tools: Sequence[BaseTool]) -> ToolNode:
    """Create a tool executor with shared validation and execution feedback."""
    return ToolNode(list(tools), handle_tool_errors=tool_error_message)
