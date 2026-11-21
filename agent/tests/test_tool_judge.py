"""Tests for the judge's conversational input format and structured outputs."""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage

from master.tool_judge import EvaluationCriteria, ToolJudge


class ResponsesModel:
    def __init__(self, responses: list[str]) -> None:
        self.responses = iter(responses)
        self.inputs: list[list[BaseMessage]] = []

    async def ainvoke(self, messages, *, config=None):
        self.inputs.append(messages)
        return AIMessage(content=next(self.responses))


@pytest.mark.asyncio
async def test_criteria_uses_conversation_messages_then_final_task_message():
    model = ResponsesModel(['{"objectives":["Find two requested facts"]}'])
    judge = ToolJudge(model, max_attempts=1)
    conversation = [
        HumanMessage(content="Find the latest index value and a local supper spot."),
        AIMessage(content="", tool_calls=[]),
    ]

    criteria = await judge.create_criteria(
        conversation,
        [{"name": "web_search", "args": {"query": "index", "priority": 1}}],
    )

    sent = model.inputs[0]
    assert isinstance(sent[0], SystemMessage)
    assert sent[1:-1] == conversation
    assert isinstance(sent[-1], HumanMessage)
    assert "initial tool calls" in sent[-1].content
    assert '"query": "index"' in sent[-1].content
    assert "Find the latest index value" not in sent[-1].content
    assert criteria == EvaluationCriteria(objectives=["Find two requested facts"])


@pytest.mark.asyncio
async def test_evaluation_receives_normal_tool_messages_and_final_criteria():
    model = ResponsesModel(
        [
            '{"objectives":["Find the answer"]}',
            '{"grade":"A","decision":"continue","comment":"The results answer the request."}',
        ]
    )
    judge = ToolJudge(model, max_attempts=1)
    conversation = [
        HumanMessage(content="Find the answer."),
        AIMessage(content="", tool_calls=[]),
        ToolMessage(content="The requested result.", tool_call_id="call-1"),
    ]
    criteria = await judge.create_criteria(conversation[:1], [])
    verdict = await judge.evaluate(conversation, criteria, [])

    sent = model.inputs[1]
    assert sent[1:-1] == conversation
    assert isinstance(sent[-1], HumanMessage)
    assert "Remaining queued tool calls" in sent[-1].content
    assert "The requested result" not in sent[-1].content
    assert verdict.grade == "A"
    assert verdict.comment == "The results answer the request."
