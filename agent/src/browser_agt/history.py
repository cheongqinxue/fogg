"""Compact browser observation payloads before sending graph history to the model."""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from typing import Any

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, ToolMessage

MAX_FULL_OBSERVATIONS_IN_CONTEXT = 2
_OMITTED_TEXT = "[Observation text omitted from context; retrieve it by observation_id.]"
MAX_CURRENT_OBSERVATION_TEXT_CHARS = 8_000
MAX_CURRENT_OBSERVATION_ELEMENTS = 40


def _reference(record: dict[str, Any]) -> dict[str, Any]:
    """Keep a usable pointer while removing the large page body and controls."""
    reference = {
        "observation_id": record["observation_id"],
        "url": record.get("url"),
        "title": record.get("title"),
        "text": _OMITTED_TEXT,
        "elements": [],
        "reference_only": True,
    }
    if "is_current_page" in record:
        reference["is_current_page"] = record["is_current_page"]
    if "error" in record:
        reference["error"] = record["error"]
    return reference


def compact_observation_history(messages: Sequence[BaseMessage]) -> list[BaseMessage]:
    """Keep the two most recently exposed snapshots full and reference older ones.

    The original graph state is not mutated. Tool-call messages and their IDs remain
    intact; only old observation tool-result content is compacted for model input.
    """
    occurrences: list[tuple[int, int, str]] = []
    parsed_by_message: dict[int, tuple[dict[str, Any], list[dict[str, Any]]]] = {}
    for message_index, message in enumerate(messages):
        if not isinstance(message, ToolMessage) or not isinstance(message.content, str):
            continue
        try:
            payload = json.loads(message.content)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and isinstance(payload.get("observation_id"), str):
            records = [payload]
        elif isinstance(payload, dict) and isinstance(payload.get("observations"), list):
            records = [
                item
                for item in payload["observations"]
                if isinstance(item, dict) and isinstance(item.get("observation_id"), str)
            ]
        else:
            continue
        parsed_by_message[message_index] = (payload, records)
        for record_index, record in enumerate(records):
            occurrences.append((message_index, record_index, record["observation_id"]))

    if not occurrences:
        return list(messages)

    last_occurrence: dict[str, tuple[int, int]] = {
        observation_id: (message_index, record_index)
        for message_index, record_index, observation_id in occurrences
    }
    recent_ids = set(
        sorted(last_occurrence, key=last_occurrence.get)[-MAX_FULL_OBSERVATIONS_IN_CONTEXT:]
    )
    compacted = list(messages)
    for message_index, (payload, records) in parsed_by_message.items():
        original_content = messages[message_index].content
        decoded = json.loads(original_content)
        if isinstance(decoded.get("observation_id"), str):
            record = records[0]
            if record["observation_id"] not in recent_ids or last_occurrence[
                record["observation_id"]
            ] != (message_index, 0):
                decoded = _reference(record)
        else:
            rewritten_records = []
            for record_index, record in enumerate(records):
                observation_id = record["observation_id"]
                if observation_id in recent_ids and last_occurrence[observation_id] == (
                    message_index,
                    record_index,
                ):
                    rewritten_records.append(record)
                else:
                    rewritten_records.append(_reference(record))
            decoded["observations"] = rewritten_records
        compacted[message_index] = messages[message_index].model_copy(
            update={"content": json.dumps(decoded, ensure_ascii=False)}
        )
    return compacted


def prepare_browser_model_messages(
    messages: list[BaseMessage],
    max_tokens: int,
    token_counter: Callable[[Sequence[BaseMessage]], int],
) -> list[BaseMessage]:
    """Keep the original task and newest screenshot while trimming older history.

    Browser research has one user request followed by an unbounded action transcript.
    Generic trimming can remove the entire transcript when that only human message is
    at the beginning. Pin the request and newest screenshot, then fit recent context
    into the remaining budget.
    """
    system_index = next(
        (index for index, message in enumerate(messages) if isinstance(message, SystemMessage)),
        None,
    )
    human_index = next(
        (index for index, message in enumerate(messages) if isinstance(message, HumanMessage)),
        None,
    )
    if system_index is None or human_index is None:
        raise ValueError("Browser context requires a system prompt and original request")

    observations: list[tuple[int, dict[str, Any]]] = []
    for index, message in enumerate(messages):
        if not isinstance(message, ToolMessage) or not isinstance(message.content, str):
            continue
        try:
            payload = json.loads(message.content)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and isinstance(payload.get("observation_id"), str):
            observations.append((index, payload))
    if not observations:
        raise ValueError("Browser context requires a screenshot observation")

    current_index, current_payload = observations[-1]
    screenshot = current_payload.get("screenshot")
    if not isinstance(screenshot, str) or not screenshot:
        raise ValueError("The latest browser observation has no screenshot")

    bounded_payload = dict(current_payload)
    bounded_payload["text"] = str(bounded_payload.get("text", ""))[
        :MAX_CURRENT_OBSERVATION_TEXT_CHARS
    ]
    elements = bounded_payload.get("elements", [])
    if isinstance(elements, list):
        bounded_payload["elements"] = [
            {**item, "label": str(item.get("label", ""))[:160]}
            for item in elements[:MAX_CURRENT_OBSERVATION_ELEMENTS]
            if isinstance(item, dict)
        ]
    current_message = messages[current_index].model_copy(
        update={"content": json.dumps(bounded_payload, ensure_ascii=False)}
    )
    system_message = messages[system_index]
    original_request = messages[human_index]
    mandatory = [system_message, original_request, current_message]

    if token_counter(mandatory) > max_tokens:
        bounded_payload["text"] = ""
        bounded_payload["elements"] = []
        current_message = messages[current_index].model_copy(
            update={"content": json.dumps(bounded_payload, ensure_ascii=False)}
        )
        mandatory = [system_message, original_request, current_message]
    if token_counter(mandatory) > max_tokens:
        raise ValueError("The original request and latest screenshot exceed the model input budget")

    selected_indices = {human_index, current_index}
    for index in range(len(messages) - 1, -1, -1):
        if index in selected_indices or index == system_index:
            continue
        candidate_indices = sorted((*selected_indices, index))
        candidate = [
            current_message if item_index == current_index else messages[item_index]
            for item_index in candidate_indices
        ]
        if token_counter([system_message, *candidate]) <= max_tokens:
            selected_indices.add(index)

    retained = [
        current_message if index == current_index else messages[index]
        for index in sorted(selected_indices)
    ]
    return [system_message, *retained]
