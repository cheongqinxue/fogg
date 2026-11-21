"""Tests for the explicit ReAct model/tool graph."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence

import pytest
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import MemorySaver

from master import agent as agent_module


class FakeModel:
    def __init__(self, responses: Sequence[AIMessage]) -> None:
        self.responses = iter(responses)
        self.received: list[list[BaseMessage]] = []

    def bind_tools(self, _tools):
        return self

    async def ainvoke(self, messages: list[BaseMessage]) -> AIMessage:
        self.received.append(messages)
        return next(self.responses)

    def get_num_tokens_from_messages(self, messages: list[BaseMessage]) -> int:
        return len(messages)


@pytest.mark.asyncio
async def test_model_node_trims_history_and_keeps_system_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from langchain_core.messages import SystemMessage
    from master.nodes import build_model_node

    monkeypatch.setenv("AGENT_MAX_INPUT_TOKENS", "3")
    model = FakeModel([AIMessage(content="Ready")])
    node = build_model_node(model, system_prompt="Follow these instructions", token_counter=len)
    state = {
        "messages": [
            HumanMessage(content="old"),
            AIMessage(content="old reply"),
            HumanMessage(content="latest"),
        ]
    }
    await node(state)
    received = model.received[0]
    assert isinstance(received[0], SystemMessage)
    assert received[-1].content == "latest"
    assert len(received) <= 3
    assert all(message.content != "old" for message in received)


@pytest.mark.asyncio
async def test_model_node_preserves_latest_user_request_when_tool_history_overflows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from master.nodes import build_model_node

    monkeypatch.setenv("AGENT_MAX_INPUT_TOKENS", "80")
    model = FakeModel([AIMessage(content="I will continue the requested research.")])

    def count_content(messages: Sequence[BaseMessage]) -> int:
        return sum(len(str(message.content)) for message in messages)

    node = build_model_node(
        model,
        system_prompt="system",
        token_counter=count_content,
    )
    request = HumanMessage(content="Research where locals in Busan go for supper.")
    state = {
        "messages": [
            request,
            AIMessage(content=""),
            ToolMessage(content="search result " * 100, tool_call_id="search-1"),
        ]
    }

    await node(state)

    received = model.received[0]
    assert received[0].content == "system"
    assert any(message is request for message in received)
    assert "Busan" in str(next(message.content for message in received if message is request))


@pytest.mark.asyncio
async def test_graph_runs_model_tool_model_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    model = FakeModel(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "echo_destination",
                        "args": {"name": "Paris", "priority": 1},
                        "id": "call-1",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(content="Noted Paris for your trip."),
        ]
    )
    monkeypatch.setattr(agent_module, "get_llm", lambda: model)
    monkeypatch.setattr("master.nodes.trim_messages", lambda messages, **_kwargs: messages)
    monkeypatch.setattr(agent_module, "get_checkpointer", lambda: MemorySaver())
    graph = agent_module.build_graph()

    result = await asyncio.wait_for(
        graph.ainvoke(
            {"messages": [HumanMessage(content="Remember Paris")]},
            config={"configurable": {"thread_id": "react-test"}},
        ),
        timeout=2,
    )

    messages = result["messages"]
    assert any(isinstance(message, ToolMessage) for message in messages)
    assert messages[-1].content == "Noted Paris for your trip."


@pytest.mark.asyncio
async def test_graph_ends_when_model_does_not_request_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = FakeModel([AIMessage(content="Hello.")])
    monkeypatch.setattr(agent_module, "get_llm", lambda: model)
    monkeypatch.setattr("master.nodes.trim_messages", lambda messages, **_kwargs: messages)
    monkeypatch.setattr(agent_module, "get_checkpointer", lambda: MemorySaver())
    graph = agent_module.build_graph()

    result = await asyncio.wait_for(
        graph.ainvoke(
            {"messages": [HumanMessage(content="Hi")]},
            config={"configurable": {"thread_id": "react-final-test"}},
        ),
        timeout=2,
    )

    assert result["messages"][-1].content == "Hello."


async def _run_tool_error_graph(monkeypatch, test_tool, args):
    from langchain_core.messages import AIMessage
    from langgraph.graph import END, START, MessagesState, StateGraph

    from master.nodes import build_tool_node

    tool_call = AIMessage(
        content="",
        tool_calls=[
            {
                "name": test_tool.name,
                "args": {"priority": 1, **args},
                "id": "tool-error-call",
                "type": "tool_call",
            }
        ],
    )
    monkeypatch.setattr("master.nodes.get_tools", lambda: [test_tool])
    observed_by_agent = []

    async def agent_node(state):
        observed_by_agent.extend(
            message for message in state["messages"] if isinstance(message, ToolMessage)
        )
        return {}

    builder = StateGraph(MessagesState)
    builder.add_node("tools", build_tool_node())
    builder.add_node("agent", agent_node)
    builder.add_edge(START, "tools")
    builder.add_edge("tools", "agent")
    builder.add_edge("agent", END)
    graph = builder.compile()
    await graph.ainvoke({"messages": [tool_call]})
    return observed_by_agent


@pytest.mark.asyncio
async def test_validation_error_is_returned_to_agent_with_retry_guidance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from langchain_core.tools import tool
    from pydantic import Field

    from utils.tools import PrioritizedToolInput

    class StrictCountInput(PrioritizedToolInput):
        count: int = Field(description="Integer count required by this test tool.")

    @tool(args_schema=StrictCountInput)
    async def count_tool(count: int, priority: int) -> str:
        """Return the count supplied to the test tool."""
        return str(count)

    tool_messages = await _run_tool_error_graph(
        monkeypatch, count_tool, {"count": "not-an-integer", "priority": 1}
    )

    assert len(tool_messages) == 1
    assert tool_messages[0].status == "error"
    assert "count" in str(tool_messages[0].content)
    assert "Correct the invalid arguments and retry" in str(tool_messages[0].content)


@pytest.mark.asyncio
async def test_execution_error_is_returned_without_retry_instruction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from langchain_core.tools import tool
    from pydantic import Field

    from utils.tools import PrioritizedToolInput

    class FailingInput(PrioritizedToolInput):
        name: str = Field(description="Name parameter accepted by this test tool.")

    @tool(args_schema=FailingInput)
    async def failing_tool(name: str, priority: int) -> str:
        """Raise a predictable test execution error."""
        raise RuntimeError("service temporarily unavailable")

    tool_messages = await _run_tool_error_graph(
        monkeypatch, failing_tool, {"name": "Paris", "priority": 1}
    )

    assert len(tool_messages) == 1
    assert tool_messages[0].status == "error"
    assert "RuntimeError" in str(tool_messages[0].content)
    assert "service temporarily unavailable" in str(tool_messages[0].content)
    assert "retry" not in str(tool_messages[0].content).lower()
    assert "choose another approach" in str(tool_messages[0].content)


@pytest.mark.asyncio
async def test_disabled_tool_is_not_executed_and_error_returns_to_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from langchain_core.tools import tool
    from pydantic import Field

    from utils.tools import PrioritizedToolInput

    calls: list[str] = []

    class DisabledToolInput(PrioritizedToolInput):
        name: str = Field(description="Name used by the disabled-tool regression test.")

    @tool(args_schema=DisabledToolInput)
    async def disabled_test_tool(name: str, priority: int) -> str:
        """Tool that must not execute while disabled."""
        calls.append(name)
        return name

    async def no_active_tools(_uid: str, *, tools=None):
        return []

    monkeypatch.setattr("master.nodes.get_active_tools", no_active_tools)

    tool_messages = await _run_tool_error_graph(
        monkeypatch, disabled_test_tool, {"name": "must-not-run", "priority": 1}
    )

    assert calls == []
    assert len(tool_messages) == 1
    assert tool_messages[0].status == "error"
    assert "disabled for this user" in str(tool_messages[0].content)
    assert "another available tool" in str(tool_messages[0].content)


async def _run_tool_batch(monkeypatch, test_tool, calls):
    from langchain_core.messages import AIMessage
    from langgraph.graph import END, START, MessagesState, StateGraph

    from master.nodes import build_tool_node

    monkeypatch.setattr("master.nodes.get_tools", lambda: [test_tool])

    async def active_tools(_uid: str, *, tools=None):
        return [test_tool]

    monkeypatch.setattr("master.nodes.get_active_tools", active_tools)
    tool_call_message = AIMessage(content="", tool_calls=calls)
    observed: list[ToolMessage] = []

    async def agent_node(state):
        observed.extend(
            message for message in state["messages"] if isinstance(message, ToolMessage)
        )
        return {}

    builder = StateGraph(MessagesState)
    builder.add_node("tools", build_tool_node())
    builder.add_node("agent", agent_node)
    builder.add_edge(START, "tools")
    builder.add_edge("tools", "agent")
    builder.add_edge("agent", END)
    await builder.compile().ainvoke({"messages": [tool_call_message]})
    return observed


@pytest.mark.asyncio
async def test_parallel_tool_calls_execute_in_ascending_priority_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from langchain_core.tools import tool
    from pydantic import Field

    from utils.tools import PrioritizedToolInput

    execution_order: list[str] = []

    class OrderedInput(PrioritizedToolInput):
        value: str = Field(description="Value used to record execution order.")

    @tool(args_schema=OrderedInput)
    async def record_order(value: str, priority: int) -> str:
        """Record a value so this test can inspect call execution order."""
        execution_order.append(value)
        return value

    tool_messages = await _run_tool_batch(
        monkeypatch,
        record_order,
        [
            {
                "name": "record_order",
                "args": {"value": "second", "priority": 2},
                "id": "call-2",
                "type": "tool_call",
            },
            {
                "name": "record_order",
                "args": {"value": "first", "priority": 1},
                "id": "call-1",
                "type": "tool_call",
            },
        ],
    )

    assert execution_order == ["first", "second"]
    assert [message.tool_call_id for message in tool_messages] == ["call-2", "call-1"]
    assert all(message.status != "error" for message in tool_messages)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "args",
    [
        [{"value": "one", "priority": 1}, {"value": "two", "priority": 1}],
        [{"value": "one", "priority": 1}, {"value": "two"}],
    ],
    ids=["duplicate", "missing"],
)
async def test_parallel_tool_calls_with_invalid_priorities_return_retry_guidance(
    monkeypatch: pytest.MonkeyPatch,
    args: list[dict[str, object]],
) -> None:
    from langchain_core.tools import tool
    from pydantic import Field

    from utils.tools import PrioritizedToolInput

    execution_order: list[str] = []

    class OrderedInput(PrioritizedToolInput):
        value: str = Field(description="Value used to record whether execution happened.")

    @tool(args_schema=OrderedInput)
    async def record_order(value: str, priority: int) -> str:
        """Record an unexpected execution in this validation test."""
        execution_order.append(value)
        return value

    calls = [
        {"name": "record_order", "args": call_args, "id": f"call-{index}", "type": "tool_call"}
        for index, call_args in enumerate(args, start=1)
    ]
    messages = await _run_tool_batch(monkeypatch, record_order, calls)

    assert execution_order == []
    assert len(messages) == 2
    assert all(message.status == "error" for message in messages)
    assert all("positive integer `priority`" in str(message.content) for message in messages)
    assert all("retry the call or batch" in str(message.content) for message in messages)


def test_every_registered_tool_schema_exposes_priority() -> None:
    from master.tools import get_tools

    assert all("priority" in tool.args_schema.model_fields for tool in get_tools())
    assert all(tool.args_schema.model_fields["priority"].is_required() for tool in get_tools())


@pytest.mark.asyncio
async def test_single_tool_call_must_include_priority(monkeypatch: pytest.MonkeyPatch) -> None:
    from langchain_core.tools import tool
    from pydantic import Field

    from utils.tools import PrioritizedToolInput

    executions: list[str] = []

    class RequiredPriorityInput(PrioritizedToolInput):
        value: str = Field(description="Value recorded if execution proceeds.")

    @tool(args_schema=RequiredPriorityInput)
    async def record(value: str, priority: int) -> str:
        """Record the tool execution for this regression test."""
        executions.append(value)
        return value

    messages = await _run_tool_batch(
        monkeypatch,
        record,
        [{"name": "record", "args": {"value": "missing"}, "id": "call-1", "type": "tool_call"}],
    )

    assert executions == []
    assert len(messages) == 1
    assert messages[0].status == "error"
    assert "Every tool call needs a positive integer `priority`" in str(messages[0].content)
