"""Priority-aware execution and evaluation of master-agent tool batches."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import uuid4

from langchain_core.callbacks.manager import adispatch_custom_event
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool
from langgraph.prebuilt import ToolNode
from langgraph.prebuilt.tool_node import ToolInvocationError

from master.tools import LIMITED_CONCURRENCY_TOOL_NAMES
from master.tool_judge import (
    EvaluationCriteria,
    ToolJudge,
    ToolJudgeVerdict,
)
from utils.settings import get_settings

logger = logging.getLogger(__name__)


def _priority(call: dict[str, Any]) -> int | None:
    args = call.get("args")
    value = args.get("priority") if isinstance(args, dict) else None
    if isinstance(value, int) and not isinstance(value, bool) and value >= 1:
        return value
    return None


def _blocked_tool_message(call: dict[str, Any]) -> ToolMessage:
    name = call.get("name")
    return ToolMessage(
        content=(
            f"Tool {name!r} is disabled for this user or unavailable. "
            "Explain that it is unavailable or choose another available tool."
        ),
        tool_call_id=call["id"],
        name=name,
        status="error",
    )


def _skipped_tool_message(call: dict[str, Any], reason: str) -> ToolMessage:
    return ToolMessage(
        content=f"Tool call was not executed: {reason}",
        tool_call_id=call["id"],
        name=call.get("name"),
        status="success",
    )


async def _dispatch_event(name: str, payload: dict[str, Any], config: RunnableConfig) -> None:
    """Emit optional SSE/tracing progress without affecting tool execution."""
    try:
        await adispatch_custom_event(name, payload, config=config)
    except Exception:
        logger.debug("Could not dispatch %s progress event", name, exc_info=True)


class PriorityToolExecutor(ToolNode):
    """Run tool calls by priority, judge overflow, and preserve all call outcomes."""

    def __init__(
        self,
        tools: list[BaseTool],
        *,
        judge: ToolJudge | Any | None = None,
        max_concurrency: int | None = None,
        active_tool_selector: Callable[[list[BaseTool]], Awaitable[list[BaseTool]]] | None = None,
    ) -> None:
        registered_tools = list(tools)
        super().__init__(registered_tools, handle_tool_errors=_tool_error_message)
        self.tools = registered_tools
        self.judge = judge
        self.max_concurrency = (
            get_settings().agent_limited_tool_max_concurrency
            if max_concurrency is None
            else max_concurrency
        )
        self.active_tool_selector = active_tool_selector
        if self.max_concurrency < 1:
            raise ValueError("max_concurrency must be at least 1")

    def _judge(self) -> ToolJudge | Any:
        if self.judge is None:
            self.judge = ToolJudge()
        return self.judge

    async def _execute_calls(
        self,
        state: dict[str, Any],
        calls: list[dict[str, Any]],
        *,
        config: RunnableConfig,
        runtime: Any,
    ) -> dict[str, ToolMessage]:
        if not calls:
            return {}
        messages: list[BaseMessage] = state.get("messages") or []
        assistant_message = messages[-1].model_copy(update={"tool_calls": calls})
        result = await super()._afunc(
            {**state, "messages": [*messages[:-1], assistant_message]}, config, runtime
        )
        return {
            message.tool_call_id: message
            for message in result.get("messages", [])
            if isinstance(message, ToolMessage)
        }

    async def _judge_wave(
        self,
        judge: Any,
        wave_id: str,
        messages: list[BaseMessage],
        criteria: EvaluationCriteria,
        pending_calls: list[dict[str, Any]],
        *,
        config: RunnableConfig,
    ) -> ToolJudgeVerdict:
        await _dispatch_event(
            "evaluation_progress",
            {"wave_id": wave_id, "phase": "judging", "status": "started"},
            config,
        )
        try:
            verdict = await judge.evaluate(
                messages,
                criteria,
                pending_calls,
            )
        except Exception:
            await _dispatch_event(
                "evaluation_progress",
                {"wave_id": wave_id, "phase": "judging", "status": "failed"},
                config,
            )
            raise
        await _dispatch_event(
            "evaluation_progress",
            {"wave_id": wave_id, "phase": "judging", "status": "completed"},
            config,
        )
        await _dispatch_event(
            "evaluation_comment",
            {"wave_id": wave_id, "comment": verdict.comment},
            config,
        )
        return verdict

    async def _afunc(
        self, state: dict[str, Any], config: RunnableConfig, runtime: Any
    ) -> dict[str, Any]:
        messages: list[BaseMessage] = state.get("messages") or []
        last_message = messages[-1] if messages else None
        calls: list[dict[str, Any]] = getattr(last_message, "tool_calls", None) or []
        if not calls or last_message is None:
            return {"messages": []}

        priorities = [_priority(call) for call in calls]
        if any(priority is None for priority in priorities) or len(set(priorities)) != len(calls):
            error_content = (
                "Every tool call needs a positive integer `priority`; priorities must be "
                "unique within the assistant's tool-call batch. Use 1 for the most important "
                "call. Correct the priorities and retry the call or batch."
            )
            return {
                "messages": [
                    ToolMessage(
                        content=error_content,
                        tool_call_id=call["id"],
                        name=call.get("name"),
                        status="error",
                    )
                    for call in calls
                ]
            }

        active_tools = await self._active_tools()
        active_names = {tool.name for tool in active_tools}
        registered_names = {tool.name for tool in self.tools}
        known_active = active_names & registered_names
        ordered_calls = sorted(calls, key=lambda call: _priority(call) or 1)
        results: dict[str, ToolMessage] = {}
        active_calls = []
        for call in ordered_calls:
            if call.get("name") not in known_active:
                results[call["id"]] = _blocked_tool_message(call)
            else:
                active_calls.append(call)

        limited_calls = [
            call for call in active_calls if call.get("name") in LIMITED_CONCURRENCY_TOOL_NAMES
        ]
        unlimited_calls = [
            call for call in active_calls if call.get("name") not in LIMITED_CONCURRENCY_TOOL_NAMES
        ]
        if len(limited_calls) <= self.max_concurrency:
            results.update(
                await self._execute_calls(state, active_calls, config=config, runtime=runtime)
            )
            return {"messages": [results[call["id"]] for call in calls]}

        judge = self._judge()
        feedback: list[str] = []
        first_wave_id = uuid4().hex
        await _dispatch_event(
            "evaluation_progress",
            {
                "wave_id": first_wave_id,
                "phase": "criteria_generation",
                "status": "started",
            },
            config,
        )
        criteria_task = asyncio.create_task(judge.create_criteria(messages, ordered_calls))
        first_limited = limited_calls[: self.max_concurrency]
        first_wave = sorted(
            [*unlimited_calls, *first_limited], key=lambda call: _priority(call) or 1
        )
        try:
            first_wave_results = await self._execute_calls(
                state, first_wave, config=config, runtime=runtime
            )
        except BaseException:
            await asyncio.gather(criteria_task, return_exceptions=True)
            raise
        results.update(first_wave_results)

        try:
            criteria = await criteria_task
        except Exception:
            await _dispatch_event(
                "evaluation_progress",
                {
                    "wave_id": first_wave_id,
                    "phase": "criteria_generation",
                    "status": "failed",
                },
                config,
            )
            feedback.append(
                "Evaluation criteria could not be generated after retries. Tool results are "
                "preserved and the queued limited-concurrency calls were executed in priority "
                "order. Use the observed outputs to decide whether further research is needed."
            )
            for offset in range(self.max_concurrency, len(limited_calls), self.max_concurrency):
                wave = limited_calls[offset : offset + self.max_concurrency]
                results.update(
                    await self._execute_calls(state, wave, config=config, runtime=runtime)
                )
        else:
            await _dispatch_event(
                "evaluation_progress",
                {
                    "wave_id": first_wave_id,
                    "phase": "criteria_generation",
                    "status": "completed",
                },
                config,
            )
            executed_limited = len(first_limited)
            working_messages = self._messages_with_results(messages, calls, results)
            verdict_history: list[str] = []
            wave_id = first_wave_id

            while True:
                pending = limited_calls[executed_limited:]
                try:
                    verdict = await self._judge_wave(
                        judge,
                        wave_id,
                        working_messages,
                        criteria,
                        pending,
                        config=config,
                    )
                except Exception:
                    feedback.append(
                        "Tool evaluation failed after retries. Existing results are preserved "
                        "and the remaining queued limited-concurrency calls were executed in "
                        "priority order. Use their outputs to decide what to do next."
                    )
                    for offset in range(executed_limited, len(limited_calls), self.max_concurrency):
                        wave = limited_calls[offset : offset + self.max_concurrency]
                        results.update(
                            await self._execute_calls(state, wave, config=config, runtime=runtime)
                        )
                        executed_limited += len(wave)
                        working_messages = self._messages_with_results(messages, calls, results)
                    break

                decision = "stop" if verdict.grade == "A" else verdict.decision
                verdict_history.append(
                    f"Grade {verdict.grade}; action {decision}; judge comment: {verdict.comment}"
                )
                if verdict.grade == "A":
                    for call in pending:
                        results[call["id"]] = _skipped_tool_message(
                            call,
                            "the judge found the collected results sufficient; use those results to answer.",
                        )
                    break
                if decision == "replan":
                    for call in pending:
                        results[call["id"]] = _skipped_tool_message(
                            call,
                            "the judge recommends changing the search approach; review its feedback before choosing new calls.",
                        )
                    break
                if not pending:
                    feedback.append(
                        "The judge recommends continuing, but the original priority queue is "
                        "exhausted. Review the judge feedback and replan if more evidence is needed."
                    )
                    break

                wave = pending[: self.max_concurrency]
                results.update(
                    await self._execute_calls(state, wave, config=config, runtime=runtime)
                )
                executed_limited += len(wave)
                working_messages = self._messages_with_results(messages, calls, results)
                wave_id = uuid4().hex

            if verdict_history:
                feedback.append(self._format_verdict_history(verdict_history))

        update: dict[str, Any] = {"messages": [results[call["id"]] for call in calls]}
        if feedback:
            update["tool_judge_feedback"] = "\n\n".join(feedback)
        return update

    async def _active_tools(self) -> list[BaseTool]:
        """Override point for request-scoped activation in the master node builder."""
        if self.active_tool_selector is None:
            return self.tools
        return await self.active_tool_selector(self.tools)

    @staticmethod
    def _messages_with_results(
        messages: list[BaseMessage],
        calls: list[dict[str, Any]],
        results: dict[str, ToolMessage],
    ) -> list[BaseMessage]:
        executed_calls = [call for call in calls if call["id"] in results]
        conversation = list(messages)
        if conversation and isinstance(conversation[-1], AIMessage):
            assistant_message = conversation[-1]
            conversation[-1] = AIMessage(
                content=assistant_message.content,
                tool_calls=executed_calls,
                id=assistant_message.id,
                name=assistant_message.name,
                response_metadata=assistant_message.response_metadata,
            )
        return [*conversation, *(results[call["id"]] for call in executed_calls)]

    @staticmethod
    def _format_verdict_history(verdicts: list[str]) -> str:
        return "Search evaluation feedback for the master agent:\n" + "\n".join(
            f"- {verdict}" for verdict in verdicts
        )


__all__ = ["PriorityToolExecutor"]


def _tool_error_message(error: Exception) -> str:
    if isinstance(error, ToolInvocationError):
        return (
            f"{error.message}\nCorrect the invalid arguments and retry the tool call; "
            "do not repeat the same invalid arguments."
        )
    return (
        f"Tool execution failed ({type(error).__name__}): {error}. "
        "Use this information to explain the failure or choose another approach."
    )
