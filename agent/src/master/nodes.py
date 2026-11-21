"""Master agent nodes backed by the reusable LangGraph utilities."""

from __future__ import annotations

from typing import Any

from langchain_core.messages import SystemMessage, trim_messages
from utils.langgraph import build_model_node as _build_model_node
from utils.request_context import request_account_id

from master.tool_execution import PriorityToolExecutor
from master.tools import get_active_tools, get_tools


def build_model_node(
    model: Any,
    *,
    system_prompt: str,
    token_counter: Any,
    tools=None,
):
    """Build a request-scoped model node that receives private judge feedback."""

    async def select_tools():
        return await get_active_tools(
            request_account_id.get(None), tools=get_tools() if tools is None else tools
        )

    model_node = _build_model_node(
        model,
        system_prompt=system_prompt,
        token_counter=token_counter,
        trim_messages_fn=trim_messages,
        tool_selector=select_tools,
        extra_context_selector=lambda state: (
            [
                SystemMessage(
                    content=(
                        "Internal tool-judge feedback (not a user message):\n"
                        f"{state['tool_judge_feedback']}"
                    )
                )
            ]
            if state.get("tool_judge_feedback")
            else []
        ),
    )

    async def call_model(state):
        messages = state.get("messages") or []
        # Older checkpoints may still contain synthetic viewport-action messages.
        # They are no longer part of the agent's product context.
        model_state = {
            **state,
            "messages": [
                message
                for message in messages
                if (getattr(message, "additional_kwargs", None) or {}).get("kind") != "user_action"
            ],
        }
        result = await model_node(model_state)
        return {**result, "tool_judge_feedback": None}

    return call_model


def build_tool_node(
    tools=None,
    *,
    judge=None,
    max_concurrency: int | None = None,
):
    """Build a priority scheduler with request-scoped tool activation."""
    registered_tools = list(get_tools() if tools is None else tools)

    async def select_active_tools(candidate_tools):
        return await get_active_tools(request_account_id.get(None), tools=candidate_tools)

    executor = PriorityToolExecutor(
        registered_tools,
        judge=judge,
        max_concurrency=max_concurrency,
        active_tool_selector=select_active_tools,
    )

    return executor


__all__ = ["build_model_node", "build_tool_node"]
