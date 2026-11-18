"""Tests for the explicit ReAct model/tool graph."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence

import pytest
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import MemorySaver

from master_agt import agent as agent_module


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
    from master_agt.nodes import build_model_node

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
    from master_agt.nodes import build_model_node

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
                        "args": {"name": "Paris"},
                        "id": "call-1",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(content="Noted Paris for your trip."),
        ]
    )
    monkeypatch.setattr(agent_module, "get_llm", lambda: model)
    monkeypatch.setattr("master_agt.nodes.trim_messages", lambda messages, **_kwargs: messages)
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
    monkeypatch.setattr("master_agt.nodes.trim_messages", lambda messages, **_kwargs: messages)
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

    from master_agt.nodes import build_tool_node

    tool_call = AIMessage(
        content="",
        tool_calls=[
            {
                "name": test_tool.name,
                "args": args,
                "id": "tool-error-call",
                "type": "tool_call",
            }
        ],
    )
    monkeypatch.setattr("master_agt.nodes.get_tools", lambda: [test_tool])
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

    from master_agt.tools import ToolInput

    class StrictCountInput(ToolInput):
        count: int = Field(description="Integer count required by this test tool.")

    @tool(args_schema=StrictCountInput)
    async def count_tool(count: int) -> str:
        """Return the count supplied to the test tool."""
        return str(count)

    tool_messages = await _run_tool_error_graph(
        monkeypatch, count_tool, {"count": "not-an-integer"}
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

    from master_agt.tools import ToolInput

    class FailingInput(ToolInput):
        name: str = Field(description="Name parameter accepted by this test tool.")

    @tool(args_schema=FailingInput)
    async def failing_tool(name: str) -> str:
        """Raise a predictable test execution error."""
        raise RuntimeError("service temporarily unavailable")

    tool_messages = await _run_tool_error_graph(monkeypatch, failing_tool, {"name": "Paris"})

    assert len(tool_messages) == 1
    assert tool_messages[0].status == "error"
    assert "RuntimeError" in str(tool_messages[0].content)
    assert "service temporarily unavailable" in str(tool_messages[0].content)
    assert "retry" not in str(tool_messages[0].content).lower()
    assert "choose another approach" in str(tool_messages[0].content)
