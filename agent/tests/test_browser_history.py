"""Tests for task-scoped browser observation references and context compaction."""

from __future__ import annotations

import json

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from browser_agt.history import (
    compact_observation_history,
    prepare_browser_model_messages,
)
from browser_agt.ui_tars import estimate_browser_tokens


def _observation_message(
    observation_id: str, text: str, *, screenshot: str | None = None
) -> ToolMessage:
    return ToolMessage(
        name="browser_open",
        tool_call_id=f"call-{observation_id}",
        content=json.dumps(
            {
                "observation_id": observation_id,
                "url": f"https://example.test/{observation_id}",
                "title": observation_id,
                "text": text,
                "elements": [],
                "screenshot": screenshot,
            }
        ),
    )


def _payload(message: ToolMessage) -> dict:
    return json.loads(message.content)


def test_only_two_most_recent_observations_remain_full_in_model_history() -> None:
    messages = [
        _observation_message("obs-1", "first page " * 100),
        _observation_message("obs-2", "second page " * 100),
        _observation_message("obs-3", "third page " * 100),
    ]

    compacted = compact_observation_history(messages)

    first, second, third = [_payload(message) for message in compacted]
    assert first["reference_only"] is True
    assert "first page" not in first["text"]
    assert second["text"].startswith("second page")
    assert third["text"].startswith("third page")
    assert [message.tool_call_id for message in compacted] == [
        message.tool_call_id for message in messages
    ]
    assert "first page" in _payload(messages[0])["text"]


def test_reading_old_observations_makes_them_available_and_compacts_duplicates() -> None:
    first = _observation_message("obs-1", "first page " * 100)
    second = _observation_message("obs-2", "second page " * 100)
    messages = [
        first,
        second,
        _observation_message("obs-3", "current page " * 100),
        ToolMessage(
            name="browser_read_observations",
            tool_call_id="call-read",
            content=json.dumps(
                {
                    "observations": [
                        {**_payload(first), "is_current_page": False, "elements": []},
                        {**_payload(second), "is_current_page": False, "elements": []},
                    ]
                }
            ),
        ),
    ]

    compacted = compact_observation_history(messages)

    old_first = _payload(compacted[0])
    old_second = _payload(compacted[1])
    read_result = _payload(compacted[-1])["observations"]
    assert old_first["reference_only"] is True
    assert old_second["reference_only"] is True
    assert [item["observation_id"] for item in read_result] == ["obs-1", "obs-2"]
    assert all("page" in item["text"] for item in read_result)


def test_context_preparation_pins_original_request_and_latest_screenshot() -> None:
    screenshot = "Y" * 120_000
    messages = [SystemMessage(content="Browser instructions " * 100)]
    original_query = HumanMessage(content='{"task":"Original Busan research query"}')
    messages.append(original_query)
    for index in range(40):
        messages.extend(
            [
                AIMessage(content=f"Thought: inspect page {index}; Action: scroll()"),
                _observation_message(
                    f"obs-{index}",
                    f"page content {index} " * 1_500,
                    screenshot=screenshot,
                ),
            ]
        )

    compacted = compact_observation_history(messages)
    prepared = prepare_browser_model_messages(compacted, 24_000, estimate_browser_tokens)

    assert prepared[0].content.startswith("Browser instructions")
    assert any(message is original_query for message in prepared)
    observations = [
        _payload(message)
        for message in prepared
        if isinstance(message, ToolMessage) and '"observation_id"' in message.content
    ]
    assert observations
    assert observations[-1]["observation_id"] == "obs-39"
    assert observations[-1]["screenshot"] == screenshot
    assert estimate_browser_tokens(prepared) <= 24_000


def test_context_preparation_fails_instead_of_sending_without_screenshot() -> None:
    messages = [
        SystemMessage(content="Browser instructions"),
        HumanMessage(content="Original request"),
        _observation_message("obs-1", "page without a screenshot"),
    ]

    with pytest.raises(ValueError, match="no screenshot"):
        prepare_browser_model_messages(messages, 24_000, estimate_browser_tokens)
