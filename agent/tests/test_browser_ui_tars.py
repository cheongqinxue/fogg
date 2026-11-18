"""Offline tests for UI-TARS screenshot transport and action conversion."""

from __future__ import annotations

import base64

import httpx
import pytest
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from browser_agt.ui_tars import (
    UITarsOllamaModel,
    _ollama_messages,
    _record_model_turn,
    _tool_call,
    estimate_browser_tokens,
)


def test_ui_tars_actions_are_parsed_into_visual_browser_tools() -> None:
    assert _tool_call("Thought: search\nAction: click(start_box='(177,549)')") == (
        "browser_click_at",
        {"x": 177, "y": 549},
    )
    assert _tool_call("Action: type(content='Busan locals')") == (
        "browser_type_text",
        {"value": "Busan locals"},
    )
    assert _tool_call("Action: scroll(start_box='(640,680)', direction='down')") == (
        "browser_scroll_at",
        {"x": 640, "y": 680, "direction": "down"},
    )
    assert _tool_call("Action: finished(content='Done (with a source)')") is None
    assert _tool_call("Action: python(code='import os')") is None


def test_ollama_messages_attach_image_and_strip_transport_base64() -> None:
    screenshot = base64.b64encode(b"jpeg bytes").decode("ascii")
    messages = _ollama_messages(
        [
            SystemMessage(content="Visual browser agent"),
            HumanMessage(content='{"task":"Find a cafe","starting_urls":[]}'),
            ToolMessage(
                content=(
                    '{"url":"https://example.test","title":"Example",'
                    f'"text":"visible text","screenshot":"{screenshot}"'
                    "}"
                ),
                tool_call_id="observe",
            ),
        ]
    )
    assert messages[-1]["images"] == [screenshot]
    assert screenshot not in messages[-1]["content"]
    assert "visible text" in messages[-1]["content"]


def test_browser_token_estimate_does_not_count_base64_as_text() -> None:
    image = "x" * 120_000
    message = ToolMessage(
        content=f'{{"observation_id":"one","text":"short","screenshot":"{image}"}}',
        tool_call_id="observe",
    )
    assert estimate_browser_tokens([message]) < 2000


def test_ui_tars_turn_trace_keeps_thought_action_and_screenshot_reference_only() -> None:
    screenshot = base64.b64encode(b"private screenshot bytes").decode("ascii")
    observation = ToolMessage(
        content=(
            '{"observation_id":"obs-123","url":"https://example.test/page",'
            '"title":"Example page","scroll_target":"document",'
            '"scroll_top":900,"scroll_height":1000,"client_height":720,'
            '"at_scroll_end":true,"scroll_position_changed":false,'
            f'"screenshot_changed":false,"screenshot":"{screenshot}"'
            "}"
        ),
        tool_call_id="observe",
    )
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    try:
        with provider.get_tracer("test").start_as_current_span("ui_tars.turn") as span:
            _record_model_turn(
                span,
                text="Thought: Click the visible search result.\nAction: click(start_box='(20,30)')",
                messages=[observation],
                tool_call=("browser_click_at", {"x": 20, "y": 30}),
            )
    finally:
        provider.shutdown()

    attributes = exporter.get_finished_spans()[0].attributes
    assert attributes["ui_tars.thought"] == "Click the visible search result."
    assert attributes["ui_tars.action"] == "click"
    assert attributes["ui_tars.browser_tool"] == "browser_click_at"
    assert attributes["ui_tars.observation.id"] == "obs-123"
    assert attributes["ui_tars.observation.url"] == "https://example.test/page"
    assert attributes["ui_tars.observation.screenshot"] == "true"
    assert attributes["ui_tars.observation.at_scroll_end"] is True
    assert attributes["ui_tars.observation.scroll_position_changed"] is False
    assert attributes["ui_tars.observation.screenshot_changed"] is False
    assert screenshot not in repr(attributes)


@pytest.mark.asyncio
async def test_ui_tars_model_converts_model_action_into_langgraph_tool_call() -> None:
    model = UITarsOllamaModel()
    model.tools = {"browser_click_at": object()}
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={
                "message": {"content": "Thought: Open result.\nAction: click(start_box='(17,29)')"}
            },
        )
    )
    await model.client.aclose()
    model.client = httpx.AsyncClient(transport=transport)
    try:
        result = await model.ainvoke([HumanMessage(content="Find a page")])
    finally:
        await model.aclose()

    assert result.tool_calls[0]["name"] == "browser_click_at"
    assert result.tool_calls[0]["args"] == {"x": 17, "y": 29}
