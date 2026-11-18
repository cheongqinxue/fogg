"""Regression tests for per-turn browser research budgets."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from browser_agt.agent import ResearchResult
from master_agt.browser_tool import browser_research_turn, research_web


@pytest.mark.asyncio
async def test_chat_turn_allows_initial_research_and_one_follow_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service_call = AsyncMock(
        return_value=ResearchResult(status="completed", answer="Found a source.")
    )
    monkeypatch.setattr("master_agt.browser_tool._call_research_service", service_call)

    with browser_research_turn():
        first = await research_web.ainvoke({"task": "Initial research"})
        second = await research_web.ainvoke(
            {"task": "Find the missing fact", "starting_urls": ["https://example.test"]}
        )
        third = await research_web.ainvoke({"task": "Try another search"})

    assert json.loads(first)["status"] == "completed"
    assert json.loads(second)["status"] == "completed"
    assert json.loads(third)["limitations"] == [
        "Only one focused follow-up research call is allowed per chat turn."
    ]
    assert service_call.await_count == 2
