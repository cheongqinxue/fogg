"""Offline tests for browser research and master-agent delegation."""

from __future__ import annotations

import json
import asyncio
from typing import Any

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from browser_agt.agent import research
from browser_agt.browser import ObservedElement, PageObservation
from browser_agt.agent import ResearchRequest


class FakeBrowserJob:
    """In-memory browser job with one fictional public source."""

    def __init__(self) -> None:
        self.url = "about:blank"
        self.closed = False

    async def navigate(self, url: str) -> None:
        self.url = url

    async def observe(self) -> PageObservation:
        return PageObservation(
            url=self.url, title="Example schedule", text="Bus at 09:00", elements=()
        )

    async def close(self) -> None:
        self.closed = True


class FakeRuntime:
    """Inject a browser job without a browser process or network access."""

    def __init__(self) -> None:
        self.job = FakeBrowserJob()
        self.closed = False

    async def __aenter__(self) -> FakeRuntime:
        return self

    async def __aexit__(self, *_args: Any) -> None:
        self.closed = True

    async def create_job(self) -> FakeBrowserJob:
        return self.job


class FakeResearchModel:
    """Call browser_open once, then summarize the tool result."""

    def __init__(self) -> None:
        self.calls = 0

    def bind_tools(self, _tools: Any) -> FakeResearchModel:
        return self

    async def ainvoke(self, messages: list[Any]) -> AIMessage:
        self.calls += 1
        if self.calls == 1:
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "browser_open",
                        "args": {"url": "https://example.test/schedule"},
                        "id": "browser-call",
                        "type": "tool_call",
                    }
                ],
            )
        assert any(
            isinstance(message, ToolMessage) and "Bus at 09:00" in message.content
            for message in messages
        )
        return AIMessage(content="The bus leaves at 09:00 (https://example.test/schedule).")


@pytest.mark.asyncio
async def test_research_runs_isolated_browser_graph_and_returns_sources() -> None:
    """A successful task reports only pages actually observed by the job."""
    runtime = FakeRuntime()
    result = await research(
        ResearchRequest(task="Find the bus time"),
        model=FakeResearchModel(),
        runtime_factory=lambda: runtime,
    )
    assert result.status == "completed"
    assert result.sources[0].url == "https://example.test/schedule"
    assert runtime.job.closed and runtime.closed


@pytest.mark.asyncio
async def test_browser_can_retrieve_up_to_two_stored_observations() -> None:
    from browser_agt.tools import create_browser_tools

    class TwoPageJob(FakeBrowserJob):
        async def observe(self) -> PageObservation:
            return PageObservation(
                url=self.url,
                title=self.url.rsplit("/", 1)[-1],
                text=f"Details for {self.url}",
                elements=(ObservedElement("live-id", "link", "Current link"),),
            )

    job = TwoPageJob()
    tools = {tool.name: tool for tool in create_browser_tools(job, [])}
    first = json.loads(await tools["browser_open"].ainvoke({"url": "https://example.test/first"}))
    second = json.loads(
        await tools["browser_open"].ainvoke({"url": "https://example.test/current"})
    )

    retrieved = json.loads(
        await tools["browser_read_observations"].ainvoke(
            {"observation_ids": [first["observation_id"], second["observation_id"]]}
        )
    )["observations"]

    assert len(retrieved) == 2
    assert retrieved[0]["text"] == "Details for https://example.test/first"
    assert retrieved[0]["is_current_page"] is False
    assert retrieved[0]["elements"] == []
    assert retrieved[1]["is_current_page"] is True
    assert retrieved[1]["elements"][0]["element_id"] == "live-id"


@pytest.mark.asyncio
async def test_browser_sends_updates_and_can_ask_master_for_guidance() -> None:
    from browser_agt.tools import create_browser_tools

    class FakeMasterChannel:
        def __init__(self) -> None:
            self.messages = []

        async def exchange(self, *, kind: str, payload: dict[str, Any]) -> str:
            self.messages.append((kind, payload))
            return "Focus on the local bus operator's timetable."

    channel = FakeMasterChannel()
    tools = {
        tool.name: tool
        for tool in create_browser_tools(FakeBrowserJob(), [], master_channel=channel)
    }
    observation = json.loads(
        await tools["browser_open"].ainvoke({"url": "https://example.test/transit"})
    )
    guidance = await tools["browser_ask_master"].ainvoke(
        {"question": "Which local transit provider should I check?"}
    )

    assert channel.messages[0][0] == "browser_update"
    assert channel.messages[0][1]["url"] == "https://example.test/transit"
    assert observation["master_guidance"] == "Focus on the local bus operator's timetable."
    assert channel.messages[1] == (
        "browser_guidance_request",
        {"question": "Which local transit provider should I check?"},
    )
    assert guidance == "Focus on the local bus operator's timetable."


def test_browser_observation_reader_rejects_more_than_two_ids() -> None:
    from pydantic import ValidationError

    from browser_agt.tools import ReadObservationsInput

    with pytest.raises(ValidationError):
        ReadObservationsInput.model_validate({"observation_ids": ["obs-1", "obs-2", "obs-3"]})


@pytest.mark.asyncio
async def test_research_without_observed_source_is_partial() -> None:
    """An unsupported model answer cannot be presented as sourced research."""

    class NoSourceModel(FakeResearchModel):
        async def ainvoke(self, _messages: list[Any]) -> AIMessage:
            return AIMessage(content="I think the bus leaves at nine.")

    runtime = FakeRuntime()
    result = await research(
        ResearchRequest(task="Find the bus time"),
        model=NoSourceModel(),
        runtime_factory=lambda: runtime,
    )
    assert result.status == "partial"
    assert not result.sources
    assert runtime.job.closed and runtime.closed


@pytest.mark.asyncio
async def test_timeout_closes_browser_job() -> None:
    class SlowModel(FakeResearchModel):
        async def ainvoke(self, _messages: list[Any]) -> AIMessage:
            await asyncio.sleep(60)
            return AIMessage(content="unreachable")

    runtime = FakeRuntime()
    result = await research(
        ResearchRequest(task="Find the bus time"),
        model=SlowModel(),
        runtime_factory=lambda: runtime,
        timeout_seconds=0.01,
    )
    assert result.status == "partial"
    assert result.limitations == ["Browser research time limit reached."]
    assert runtime.job.closed and runtime.closed


@pytest.mark.asyncio
async def test_graph_step_limit_is_reported_separately(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from langgraph.errors import GraphRecursionError

    class StepLimitedGraph:
        async def ainvoke(self, *_args: object, **_kwargs: object) -> None:
            raise GraphRecursionError("step limit reached")

    monkeypatch.setattr("browser_agt.agent.build_browser_graph", lambda *_args: StepLimitedGraph())
    runtime = FakeRuntime()
    result = await research(
        ResearchRequest(task="Find the bus time"),
        model=FakeResearchModel(),
        runtime_factory=lambda: runtime,
    )

    assert result.status == "partial"
    assert result.limitations == ["Browser research step limit reached."]
    assert runtime.job.closed and runtime.closed


def test_browser_events_do_not_leak_into_chat_stream() -> None:
    from api.routes.chat_handlers import _map_astream_events

    event = {"event": "on_tool_start", "name": "browser_open", "tags": ["browser_internal"]}
    assert _map_astream_events(event) == []
    event["tags"] = []
    assert _map_astream_events(event)[0]["name"] == "browser_open"


@pytest.mark.asyncio
async def test_master_research_tool_returns_structured_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Delegation passes only the requested task and returns the research result."""
    from master_agt import browser_tool
    from browser_agt.agent import ResearchResult

    async def fake_research(request: ResearchRequest) -> ResearchResult:
        assert request.task == "Find the timetable"
        return ResearchResult(
            status="partial", answer="No source found.", limitations=["No results"]
        )

    monkeypatch.setattr(browser_tool, "_call_research_service", fake_research)
    result = json.loads(await browser_tool.research_web.ainvoke({"task": "Find the timetable"}))
    assert result["status"] == "partial"
    assert result["limitations"] == ["No results"]


def test_master_can_continue_partial_research_once() -> None:
    from master_agt.agent import SYSTEM_PROMPT

    assert "make at most one focused follow-up call" in SYSTEM_PROMPT
    assert "source URLs" in SYSTEM_PROMPT


def test_master_research_deadline_exceeds_browser_task_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from master_agt.browser_tool import _timeout_seconds

    monkeypatch.setenv("BROWSER_AGENT_SERVICE_TIMEOUT_SECONDS", "200")
    assert _timeout_seconds() == 200
