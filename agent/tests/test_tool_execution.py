"""Offline tests for priority-aware tool scheduling and judging."""

from __future__ import annotations

import asyncio

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.graph import END, START, StateGraph
from pydantic import Field

from master.tool_execution import PriorityToolExecutor
from master.tool_judge import EvaluationCriteria, ToolJudgeVerdict
from master.state import AgentState
from utils.tools import PrioritizedToolInput, capture_tool_io


def _limited_tool(name: str, seen: list[str], *, delay: float = 0):
    class SearchInput(PrioritizedToolInput):
        query: str = Field(description="Search query for this offline test tool.")

    async def invoke(query: str, priority: int) -> str:
        if delay:
            await asyncio.sleep(delay)
        seen.append(query)
        return f"result: {query}"

    invoke.__name__ = name
    invoke.__doc__ = "Offline fake search tool."
    return tool(args_schema=SearchInput)(capture_tool_io(invoke))


def _call(name: str, call_id: str, priority: int, query: str = "search") -> dict:
    return {
        "name": name,
        "args": {"query": query, "priority": priority},
        "id": call_id,
        "type": "tool_call",
    }


class FakeJudge:
    def __init__(self, verdicts: list[ToolJudgeVerdict]) -> None:
        self.verdicts = iter(verdicts)
        self.criteria_calls = 0
        self.evaluations: list[tuple[list, EvaluationCriteria, list[dict]]] = []

    async def create_criteria(self, messages, initial_calls):
        self.criteria_calls += 1
        return EvaluationCriteria(objectives=["Find useful results"])

    async def evaluate(self, messages, criteria, pending_calls):
        self.evaluations.append((messages, criteria, pending_calls))
        return next(self.verdicts)


async def _run_executor(executor, messages):
    builder = StateGraph(AgentState)
    builder.add_node("tools", executor)
    builder.add_edge(START, "tools")
    builder.add_edge("tools", END)
    return await builder.compile().ainvoke({"messages": messages})


async def _stream_executor_events(executor, messages):
    builder = StateGraph(AgentState)
    builder.add_node("tools", executor)
    builder.add_edge(START, "tools")
    builder.add_edge("tools", END)
    events = []
    async for event in builder.compile().astream_events({"messages": messages}, version="v2"):
        if event["event"] == "on_custom_event":
            events.append((event["name"], event["data"]))
    return events


def _tool_messages(result):
    return [message for message in result["messages"] if isinstance(message, ToolMessage)]


@pytest.mark.asyncio
async def test_limited_overflow_runs_top_priority_then_continues_on_judge() -> None:
    seen: list[str] = []
    search = _limited_tool("places_text_search", seen)
    judge = FakeJudge(
        [
            ToolJudgeVerdict(grade="B", decision="continue", comment="Checking another source."),
            ToolJudgeVerdict(
                grade="A", decision="continue", comment="The results answer the request."
            ),
        ]
    )
    calls = [
        _call(search.name, "c3", 3, "third"),
        _call(search.name, "c1", 1, "first"),
        _call(search.name, "c2", 2, "second"),
    ]
    executor = PriorityToolExecutor([search], judge=judge, max_concurrency=1)

    result = await _run_executor(
        executor,
        [HumanMessage(content="Find useful results"), AIMessage(content="", tool_calls=calls)],
    )

    assert seen == ["first", "second"]
    assert judge.criteria_calls == 1
    assert len(judge.evaluations) == 2
    first_evaluation, second_evaluation = judge.evaluations
    first_tool_requests = next(
        message.tool_calls
        for message in first_evaluation[0]
        if isinstance(message, AIMessage) and message.tool_calls
    )
    second_tool_requests = next(
        message.tool_calls
        for message in second_evaluation[0]
        if isinstance(message, AIMessage) and message.tool_calls
    )
    assert [call["id"] for call in first_tool_requests] == ["c1"]
    assert [call["id"] for call in second_tool_requests] == ["c1", "c2"]
    tool_messages = _tool_messages(result)
    assert [m.tool_call_id for m in tool_messages] == ["c3", "c1", "c2"]
    assert "not executed" in str(tool_messages[0].content)
    assert "Checking another source" in result["tool_judge_feedback"]
    assert "The results answer the request" in result["tool_judge_feedback"]


@pytest.mark.asyncio
async def test_criteria_generation_runs_concurrently_and_grade_a_skips_queue() -> None:
    seen: list[str] = []
    criteria_started = asyncio.Event()
    tool_started = asyncio.Event()

    class ConcurrentJudge(FakeJudge):
        async def create_criteria(self, messages, initial_calls):
            criteria_started.set()
            await tool_started.wait()
            return await super().create_criteria(messages, initial_calls)

    class SearchInput(PrioritizedToolInput):
        query: str = Field(description="Search query for this offline test tool.")

    async def delayed_invoke(query: str, priority: int) -> str:
        tool_started.set()
        await criteria_started.wait()
        seen.append(query)
        return "found it"

    delayed_invoke.__name__ = "places_search_nearby"
    delayed_invoke.__doc__ = "Offline fake search tool."
    search = tool(args_schema=SearchInput)(capture_tool_io(delayed_invoke))
    judge = ConcurrentJudge(
        [ToolJudgeVerdict(grade="A", decision="continue", comment="Enough results.")]
    )
    calls = [
        _call(search.name, "c1", 1, "first"),
        _call(search.name, "c2", 2, "second"),
    ]

    result = await asyncio.wait_for(
        _run_executor(
            PriorityToolExecutor([search], judge=judge, max_concurrency=1),
            [HumanMessage(content="Search"), AIMessage(content="", tool_calls=calls)],
        ),
        timeout=1,
    )

    assert seen == ["first"]
    assert "not executed" in str(_tool_messages(result)[1].content)
    assert judge.criteria_calls == 1


@pytest.mark.asyncio
async def test_judge_failure_preserves_results_and_fails_open() -> None:
    seen: list[str] = []
    search = _limited_tool("places_search_nearby", seen)

    class FailingJudge(FakeJudge):
        async def evaluate(self, messages, criteria, pending_calls):
            raise RuntimeError("local judge unavailable")

    calls = [
        _call(search.name, "c1", 1, "first"),
        _call(search.name, "c2", 2, "second"),
    ]
    result = await _run_executor(
        PriorityToolExecutor([search], judge=FailingJudge([]), max_concurrency=1),
        [HumanMessage(content="Search"), AIMessage(content="", tool_calls=calls)],
    )

    assert seen == ["first", "second"]
    assert [message.status for message in _tool_messages(result)] == ["success", "success"]
    assert "evaluation failed" in result["tool_judge_feedback"].lower()


@pytest.mark.asyncio
async def test_invalid_or_duplicate_priorities_block_entire_batch() -> None:
    seen: list[str] = []
    search = _limited_tool("places_text_search", seen)
    calls = [_call(search.name, "c1", 1), _call(search.name, "c2", 1)]

    result = await _run_executor(
        PriorityToolExecutor([search]), [AIMessage(content="", tool_calls=calls)]
    )

    assert seen == []
    assert all(message.status == "error" for message in _tool_messages(result))
    assert all("unique" in str(message.content) for message in _tool_messages(result))


@pytest.mark.asyncio
async def test_non_overflow_batch_does_not_invoke_judge() -> None:
    seen: list[str] = []
    search = _limited_tool("places_text_search", seen)
    judge = FakeJudge([])
    calls = [_call(search.name, "c1", 1)]

    result = await _run_executor(
        PriorityToolExecutor([search], judge=judge, max_concurrency=1),
        [HumanMessage(content="Search"), AIMessage(content="", tool_calls=calls)],
    )

    assert seen == ["search"]
    assert judge.criteria_calls == 0
    assert judge.evaluations == []
    assert isinstance(_tool_messages(result)[0], ToolMessage)


@pytest.mark.asyncio
async def test_overflow_emits_safe_evaluation_progress_and_comment_events() -> None:
    seen: list[str] = []
    search = _limited_tool("web_search", seen)
    judge = FakeJudge(
        [ToolJudgeVerdict(grade="A", decision="continue", comment="The results are sufficient.")]
    )
    events = await _stream_executor_events(
        PriorityToolExecutor([search], judge=judge, max_concurrency=1),
        [
            HumanMessage(content="Search both topics."),
            AIMessage(
                content="",
                tool_calls=[
                    _call(search.name, "call-1", 1, "first"),
                    _call(search.name, "call-2", 2, "second"),
                ],
            ),
        ],
    )

    assert [(name, data.get("phase"), data.get("status")) for name, data in events[:4]] == [
        ("evaluation_progress", "criteria_generation", "started"),
        ("evaluation_progress", "criteria_generation", "completed"),
        ("evaluation_progress", "judging", "started"),
        ("evaluation_progress", "judging", "completed"),
    ]
    assert len(events) == 5
    wave_ids = {data["wave_id"] for _, data in events}
    assert len(wave_ids) == 1
    assert events[-1] == (
        "evaluation_comment",
        {"wave_id": next(iter(wave_ids)), "comment": "The results are sufficient."},
    )
