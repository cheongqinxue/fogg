"""UI-TARS visual-action adapter for the isolated browser research graph."""

from __future__ import annotations

import ast
import json
import os
import re
from typing import Any
from uuid import uuid4

import httpx
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from agent_utils.model import estimate_tokens
from agent_utils.tracing import get_tracer


_COORDINATE_RE = re.compile(r"\(?\s*(\d+)\s*,?\s*(\d+)\s*\)?")


def _action_arguments(expression: str) -> tuple[str, dict[str, Any]] | None:
    """Parse one UI-TARS call using literal-only Python AST parsing."""
    marker = re.search(r"Action:\s*", expression, re.IGNORECASE)
    if not marker:
        return None
    action_line = expression[marker.end() :].strip().splitlines()[0]
    try:
        call = ast.parse(action_line, mode="eval").body
    except SyntaxError:
        return None
    if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Name) or call.args:
        return None
    parsed: dict[str, Any] = {}
    for keyword in call.keywords:
        if keyword.arg is None:
            return None
        try:
            parsed[keyword.arg] = ast.literal_eval(keyword.value)
        except (ValueError, TypeError):
            return None
    return call.func.id.lower(), parsed


def _coordinates(value: Any) -> tuple[int, int] | None:
    if not isinstance(value, str):
        return None
    match = _COORDINATE_RE.search(value)
    return (int(match.group(1)), int(match.group(2))) if match else None


def _tool_call(text: str) -> tuple[str, dict[str, Any]] | None:
    """Convert supported UI-TARS actions into bounded browser-worker tool calls."""
    parsed = _action_arguments(text)
    if parsed is None:
        return None
    action, args = parsed
    if action == "click":
        point = _coordinates(args.get("point") or args.get("start_box"))
        return ("browser_click_at", {"x": point[0], "y": point[1]}) if point else None
    if action == "type" and isinstance(args.get("content"), str):
        return "browser_type_text", {"value": args["content"]}
    if action == "hotkey" and isinstance(args.get("key"), str):
        return "browser_hotkey", {"key": args["key"]}
    if action == "scroll":
        point = _coordinates(args.get("point") or args.get("start_box"))
        direction = args.get("direction")
        if point and direction in {"up", "down", "left", "right"}:
            return "browser_scroll_at", {"x": point[0], "y": point[1], "direction": direction}
    if action == "wait":
        return "browser_wait", {"seconds": 2}
    return None


def _without_image(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if key != "screenshot"}


def _latest_observation(messages: list[BaseMessage]) -> dict[str, Any] | None:
    """Return the newest observation payload available to the model."""
    for message in reversed(messages):
        if not isinstance(message, ToolMessage) or not isinstance(message.content, str):
            continue
        try:
            payload = json.loads(message.content)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and isinstance(payload.get("observation_id"), str):
            return payload
    return None


def _observation_reference(messages: list[BaseMessage]) -> dict[str, str] | None:
    """Return the latest screenshot's small, trace-safe reference fields."""
    observation = _latest_observation(messages)
    if observation is None:
        return None
    return {
        "id": str(observation["observation_id"]),
        "url": str(observation.get("url", ""))[:2048],
        "title": str(observation.get("title", ""))[:300],
        "screenshot": str(bool(observation.get("screenshot"))).lower(),
    }


def _record_model_turn(
    span: Any,
    *,
    text: str,
    messages: list[BaseMessage],
    tool_call: tuple[str, dict[str, Any]] | None,
) -> None:
    """Attach bounded UI-TARS reasoning/action metadata, never image bytes."""
    thought_match = re.search(r"Thought:\s*(.*?)(?=\n\s*Action:|$)", text, re.I | re.S)
    if thought_match:
        span.set_attribute("ui_tars.thought", thought_match.group(1).strip()[:2000])
    parsed = _action_arguments(text)
    if parsed:
        span.set_attribute("ui_tars.action", parsed[0][:100])
        span.set_attribute(
            "ui_tars.action_arguments",
            json.dumps(parsed[1], ensure_ascii=False, default=str)[:2000],
        )
    if tool_call:
        span.set_attribute("ui_tars.browser_tool", tool_call[0])
        span.set_attribute(
            "ui_tars.browser_tool_arguments",
            json.dumps(tool_call[1], ensure_ascii=False, default=str)[:1000],
        )
    reference = _observation_reference(messages)
    if reference:
        for key, value in reference.items():
            span.set_attribute(f"ui_tars.observation.{key}", value)
    observation = _latest_observation(messages)
    if observation:
        for key in (
            "scroll_target",
            "scroll_top",
            "scroll_height",
            "client_height",
            "at_scroll_end",
            "scroll_position_changed",
            "screenshot_changed",
        ):
            if key in observation and observation[key] is not None:
                span.set_attribute(f"ui_tars.observation.{key}", observation[key])


def estimate_browser_tokens(messages: list[BaseMessage]) -> int:
    """Count visual snapshots as image tokens instead of their base64 transport size."""
    normalized: list[BaseMessage] = []
    image_count = 0
    for message in messages:
        if isinstance(message, ToolMessage) and isinstance(message.content, str):
            try:
                payload = json.loads(message.content)
            except json.JSONDecodeError:
                payload = None
            if isinstance(payload, dict) and isinstance(payload.get("screenshot"), str):
                image_count += 1
                message = message.model_copy(
                    update={"content": json.dumps(_without_image(payload), ensure_ascii=False)}
                )
        normalized.append(message)
    return estimate_tokens(normalized) + 1600 * image_count


def _ollama_messages(messages: list[BaseMessage]) -> list[dict[str, Any]]:
    """Translate graph history into Ollama chat messages and attach observed screenshots."""
    result: list[dict[str, Any]] = []
    for message in messages:
        if isinstance(message, SystemMessage):
            result.append({"role": "system", "content": str(message.content)})
        elif isinstance(message, HumanMessage):
            raw = str(message.content)
            try:
                request = json.loads(raw)
            except json.JSONDecodeError:
                request = None
            if isinstance(request, dict) and isinstance(request.get("task"), str):
                content = f"Research task: {request['task']}"
                urls = request.get("starting_urls") or []
                if urls:
                    content += "\nStarting URLs: " + ", ".join(urls)
            else:
                content = raw
            result.append({"role": "user", "content": content})
        elif isinstance(message, AIMessage):
            if message.content:
                result.append({"role": "assistant", "content": str(message.content)})
        elif isinstance(message, ToolMessage):
            content = str(message.content)
            images: list[str] = []
            try:
                payload = json.loads(content)
            except json.JSONDecodeError:
                payload = None
            if isinstance(payload, dict):
                screenshot = payload.get("screenshot")
                if isinstance(screenshot, str) and screenshot:
                    images.append(screenshot)
                content = json.dumps(_without_image(payload), ensure_ascii=False)
            record: dict[str, Any] = {"role": "user", "content": "Browser observation: " + content}
            if images:
                record["images"] = images
            result.append(record)
    return result


class UITarsOllamaModel:
    """Runnable-compatible adapter: UI-TARS screenshot actions become LangGraph tool calls."""

    def __init__(self) -> None:
        self.model = os.environ.get(
            "BROWSER_AGENT_MODEL", "hf.co/Mungert/UI-TARS-1.5-7B-GGUF:Q4_K_M"
        )
        self.endpoint = os.environ.get(
            "BROWSER_AGENT_OLLAMA_URL", "http://127.0.0.1:11434/api/chat"
        )
        try:
            self.context_length = max(
                4096, min(int(os.environ.get("BROWSER_AGENT_CONTEXT_LENGTH", "32768")), 32768)
            )
        except ValueError:
            self.context_length = 32768
        self.tools: dict[str, Any] = {}
        self.client = httpx.AsyncClient(timeout=httpx.Timeout(150), trust_env=False)

    def bind_tools(self, tools: list[Any], **_: Any) -> UITarsOllamaModel:
        self.tools = {tool.name: tool for tool in tools}
        return self

    async def ainvoke(self, messages: list[BaseMessage], **_: Any) -> AIMessage:
        tracer = get_tracer("fogg.browser_agt.ui_tars")
        with tracer.start_as_current_span("ui_tars.turn") as span:
            span.set_attribute("ui_tars.model", self.model)
            span.set_attribute("ui_tars.context_length", self.context_length)
            response = await self.client.post(
                self.endpoint,
                json={
                    "model": self.model,
                    "messages": _ollama_messages(messages),
                    "stream": False,
                    "options": {
                        "temperature": 0,
                        "num_ctx": self.context_length,
                        "num_predict": 600,
                    },
                },
            )
            response.raise_for_status()
            body = response.json()
            text = body.get("message", {}).get("content", "")
            if not isinstance(text, str) or not text.strip():
                span.set_attribute("ui_tars.parse_status", "empty_response")
                return AIMessage(content="UI-TARS returned an empty response.")

            parsed = _action_arguments(text)
            if parsed and parsed[0] == "finished":
                _record_model_turn(span, text=text, messages=messages, tool_call=None)
                span.set_attribute("ui_tars.parse_status", "finished")
                answer = parsed[1].get("content", "")
                return AIMessage(content=answer if isinstance(answer, str) else "")
            call = _tool_call(text)
            _record_model_turn(span, text=text, messages=messages, tool_call=call)
            if call is None or call[0] not in self.tools:
                span.set_attribute("ui_tars.parse_status", "unsupported_action")
                return AIMessage(
                    content=(
                        "UI-TARS returned an unsupported action. Use only screenshot-based click, "
                        "type, hotkey, scroll, wait, or finished actions.\n" + text[:2000]
                    )
                )
            span.set_attribute("ui_tars.parse_status", "tool_call")
            name, args = call
            return AIMessage(
                content=text,
                tool_calls=[
                    {
                        "name": name,
                        "args": args,
                        "id": f"ui-tars-{uuid4().hex}",
                        "type": "tool_call",
                    }
                ],
            )

    async def aclose(self) -> None:
        await self.client.aclose()
