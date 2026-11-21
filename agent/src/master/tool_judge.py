"""Reusable LLM-as-a-judge for evaluating limited tool-search batches."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Literal

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from utils.model import create_chat_model
from utils.settings import get_settings

logger = logging.getLogger(__name__)


class EvaluationCriteria(BaseModel):
    """Explicit objectives against which the gathered results will be judged."""

    objectives: list[str] = Field(min_length=1, max_length=12)


class ToolJudgeVerdict(BaseModel):
    """Structured evaluation and queue decision returned to the tool executor."""

    grade: Literal["A", "B", "C", "D"]
    decision: Literal["continue", "replan"]
    comment: str = Field(min_length=1, max_length=500)


class ToolJudgeUnavailable(RuntimeError):
    """Criteria generation or evaluation failed after configured attempts."""


_CRITERIA_PROMPT = """You are the tool-results evaluator for a travel assistant.

Identify explicit requirements in the latest user request, the purpose those requirements
serve in context, and what would count as meaningful progress. Treat earlier conversation
only as context for the latest request. Do not invent requirements. Represent each distinct
user objective once.
"""

_EVALUATION_PROMPT = """You judge a travel assistant's search results.

Judge only the latest user's request, using the criteria in the final instruction. Grade:
A = every objective and its purpose are fully met.
B = explicit requirements are met partly or fully, but the results are not useful for the
    request's purpose.
C = results are in the right domain but miss explicit requirements.
D = results are irrelevant.

Choose `continue` if a queued tool call can help meet an unmet objective. Choose `replan` if
the master should change approach. If no calls remain and the grade is not A, choose `replan`.
Grade A always stops the queue.

Write one short, display-safe progress comment. The comment must not contain the grade,
decision, private reasoning, criteria, credentials, or raw errors. Return one JSON object
with exactly these fields: grade, decision, comment.
"""


def _response_text(response: Any) -> str:
    if isinstance(response, str):
        return response
    if isinstance(response, BaseMessage):
        content = response.content
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "".join(
                block.get("text", "")
                for block in content
                if isinstance(block, dict) and isinstance(block.get("text"), str)
            )
        return str(content)
    if isinstance(response, BaseModel):
        return response.model_dump_json()
    content = getattr(response, "content", response)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and isinstance(block.get("text"), str)
        )
    return str(content)


def _parse_json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.removeprefix("```json").removeprefix("```")
        cleaned = cleaned.removesuffix("```").strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start < 0 or end < start:
        raise ValueError("Judge response did not contain a JSON object")
    parsed = json.loads(cleaned[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("Judge response was not a JSON object")
    return parsed


class ToolJudge:
    """Generate objectives once and judge each completed limited-tool wave."""

    def __init__(self, model: Any | None = None, *, max_attempts: int | None = None) -> None:
        self._model = model
        self.max_attempts = (
            get_settings().agent_tool_judge_max_attempts if max_attempts is None else max_attempts
        )
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")

    @property
    def model(self) -> Any:
        if self._model is None:
            self._model = create_chat_model(temperature=0).bind(
                response_format={"type": "json_object"}
            )
        return self._model

    async def _invoke_schema(
        self,
        schema: type[BaseModel],
        system_prompt: str,
        conversation: list[BaseMessage],
        final_instruction: str,
    ) -> BaseModel:
        messages = [
            SystemMessage(content=system_prompt),
            *conversation,
            HumanMessage(content=final_instruction),
        ]
        last_error: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                # Do not forward LangGraph runtime configuration to the model.
                response = await self.model.ainvoke(messages)
                text = _response_text(response)
                return schema.model_validate(_parse_json_object(text))
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "Tool judge structured call failed (attempt %d/%d): %s",
                    attempt,
                    self.max_attempts,
                    type(exc).__name__,
                )
                if attempt < self.max_attempts:
                    await asyncio.sleep(min(attempt * 0.2, 1.0))
        raise ToolJudgeUnavailable("Tool judge failed after configured attempts") from last_error

    async def create_criteria(
        self,
        messages: list[BaseMessage],
        initial_calls: list[dict[str, Any]],
    ) -> EvaluationCriteria:
        result = await self._invoke_schema(
            EvaluationCriteria,
            _CRITERIA_PROMPT,
            messages,
            (
                "Derive the evaluation criteria for the latest user request from the "
                "conversation above. Use these initial tool calls as context:\n"
                f"{json.dumps(initial_calls, ensure_ascii=False, default=str)}\n\n"
                'Return valid JSON only in this shape: {"objectives": ["..."]}.'
            ),
        )
        return EvaluationCriteria.model_validate(result)

    async def evaluate(
        self,
        messages: list[BaseMessage],
        criteria: EvaluationCriteria,
        pending_calls: list[dict[str, Any]],
    ) -> ToolJudgeVerdict:
        result = await self._invoke_schema(
            ToolJudgeVerdict,
            _EVALUATION_PROMPT,
            messages,
            (
                "Evaluate the conversation and tool results above against these criteria:\n"
                f"{criteria.model_dump_json()}\n\n"
                "Remaining queued tool calls, if any:\n"
                f"{json.dumps(pending_calls, ensure_ascii=False, default=str)}\n\n"
                "Now return valid JSON only in this shape: "
                '{"grade":"A|B|C|D","decision":"continue|replan","comment":"..."}.'
            ),
        )
        return ToolJudgeVerdict.model_validate(result)


__all__ = [
    "EvaluationCriteria",
    "ToolJudge",
    "ToolJudgeUnavailable",
    "ToolJudgeVerdict",
]
