"""HTTP chat orchestration and SSE framing for user-scoped agent routes."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.messages.base import message_to_dict, messages_to_dict
from pydantic import BaseModel, Field

from graph.agent import get_graph
from layout import client_command_from_tool_output
from layout.client_context import ClientContextPayload
from layout.store import get_layout_head, get_or_create_thread_layout
from agent_utils.request_context import request_user_id
from api.routes.chat_messages import build_turn_messages
from api.messages.store import append_message


class ChatRequest(BaseModel):
    """Single user turn for the agent (user id comes from the URL path)."""

    message: str = Field(min_length=1, description="User text for this turn.")
    client_context: ClientContextPayload | None = Field(
        default=None,
        description="Optional layout/sync hint from the browser client.",
    )


def _json_default(obj: Any) -> Any:
    if isinstance(obj, BaseMessage):
        return message_to_dict(obj)
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def _normalize_state_chunk(chunk: Any) -> Any:
    if isinstance(chunk, BaseMessage):
        return message_to_dict(chunk)
    if isinstance(chunk, dict):
        return {k: _normalize_state_chunk(v) for k, v in chunk.items()}
    if isinstance(chunk, list):
        if chunk and isinstance(chunk[0], BaseMessage):
            return messages_to_dict(chunk)
        return [_normalize_state_chunk(x) for x in chunk]
    return chunk


def serialize_chat_state(chunk: Any) -> dict[str, Any]:
    """JSON-safe graph state for blocking chat responses."""
    normalized = _normalize_state_chunk(chunk)
    return json.loads(json.dumps(normalized, default=_json_default))


def _normalize_stream_payload(obj: Any) -> Any:
    if isinstance(obj, BaseMessage):
        return message_to_dict(obj)
    if isinstance(obj, dict):
        return {k: _normalize_stream_payload(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_normalize_stream_payload(x) for x in obj]
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    return str(obj)


def _sse_data(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, default=_json_default)}\n\n"


def _tool_arguments(data: dict[str, Any]) -> dict[str, Any]:
    raw = data.get("input")
    if isinstance(raw, dict):
        return _normalize_stream_payload(raw)
    if raw is None:
        return {}
    return {"input": _normalize_stream_payload(raw)}


def _tool_output_text(output: Any) -> str | None:
    if isinstance(output, BaseMessage):
        content = output.content
        return content if isinstance(content, str) else str(content)
    if isinstance(output, str):
        return output
    if output is None:
        return None
    return str(output)


def _map_astream_events(raw_event: dict[str, Any]) -> list[dict[str, Any]]:
    kind = raw_event.get("event")
    data = raw_event.get("data") or {}
    name = raw_event.get("name")
    run_id = raw_event.get("run_id")
    run_id_str = str(run_id) if run_id is not None else None

    if kind == "on_tool_start":
        return [
            {
                "type": "tool_call_start",
                "name": name,
                "arguments": _tool_arguments(data),
                "run_id": run_id_str,
            },
        ]

    if kind == "on_tool_end":
        output = data.get("output")
        out_text = _tool_output_text(output)
        events: list[dict[str, Any]] = []
        cmd = client_command_from_tool_output(name, out_text, run_id=run_id_str)
        if cmd is not None:
            events.append(cmd)
        tool_end_event: dict[str, Any] = {
            "type": "tool_call_end",
            "name": name,
            "arguments": _tool_arguments(data),
            "run_id": run_id_str,
        }
        if out_text is not None:
            tool_end_event["output"] = out_text
        elif output is not None:
            tool_end_event["output"] = _normalize_stream_payload(output)
        tool_call_id = (
            getattr(output, "tool_call_id", None) if isinstance(output, BaseMessage) else None
        )
        if tool_call_id is not None:
            tool_end_event["tool_call_id"] = tool_call_id
        events.append(tool_end_event)
        return events

    if kind == "on_chat_model_stream":
        chunk = data.get("chunk")
        if chunk is None or not hasattr(chunk, "content"):
            return []
        delta = chunk.content
        if isinstance(delta, str) and delta:
            return [{"type": "assistant_delta", "delta": delta}]
        return []

    return []


def _langgraph_config(user_id: str) -> dict[str, Any]:
    """LangGraph configurable (checkpoint partition key)."""
    return {"configurable": {"thread_id": user_id}}


async def _assistant_done_payload(user_id: str) -> dict[str, Any]:
    head = await get_layout_head(user_id)
    if head is None:
        row = await get_or_create_thread_layout(user_id)
        return {
            "type": "assistant_done",
            "layout_revision": row.revision,
            "layout_hash": row.layout_hash,
        }
    return {
        "type": "assistant_done",
        "layout_revision": head.revision,
        "layout_hash": head.layout_hash,
    }


async def run_chat_turn(user_id: str, request: ChatRequest) -> dict[str, Any]:
    """Blocking full graph turn for one user."""
    token = request_user_id.set(user_id)
    try:
        messages = await build_turn_messages(
            message=request.message,
            user_id=user_id,
            client_context=request.client_context,
        )
        await append_message(user_id, "user", request.message)
        result = await get_graph().ainvoke(
            {"messages": messages}, config=_langgraph_config(user_id)
        )
        assistant_text = _final_assistant_text(result)
        if assistant_text is not None:
            await append_message(user_id, "assistant", assistant_text)
        return {"state": serialize_chat_state(result)}
    finally:
        request_user_id.reset(token)


async def stream_chat_events(user_id: str, request: ChatRequest) -> AsyncIterator[str]:
    """SSE frames for one chat turn."""
    graph = get_graph()
    messages = await build_turn_messages(
        message=request.message,
        user_id=user_id,
        client_context=request.client_context,
    )
    await append_message(user_id, "user", request.message)
    token = request_user_id.set(user_id)
    assistant_parts: list[str] = []
    try:
        async for raw_event in graph.astream_events(
            {"messages": messages},
            config=_langgraph_config(user_id),
            version="v2",
        ):
            for payload_obj in _map_astream_events(raw_event):
                if payload_obj.get("type") == "assistant_delta":
                    assistant_parts.append(payload_obj["delta"])
                yield _sse_data(payload_obj)
        if assistant_parts:
            await append_message(user_id, "assistant", "".join(assistant_parts))
        yield _sse_data(await _assistant_done_payload(user_id))
    finally:
        request_user_id.reset(token)


def _final_assistant_text(result: dict[str, Any]) -> str | None:
    """Extract the final user-facing assistant message from graph output."""
    for message in reversed(result.get("messages") or []):
        if not isinstance(message, AIMessage) or message.tool_calls:
            continue
        content = message.content
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "".join(
                part if isinstance(part, str) else part.get("text", "")
                for part in content
                if isinstance(part, str) or isinstance(part, dict)
            )
    return None


def chat_stream_response(user_id: str, request: ChatRequest) -> StreamingResponse:
    """StreamingResponse wrapper for chat SSE."""
    return StreamingResponse(
        stream_chat_events(user_id, request),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
