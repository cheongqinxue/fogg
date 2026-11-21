"""Shared helpers for configuring OpenAI-compatible chat models."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from langchain_core.messages import BaseMessage
from langchain_openai import ChatOpenAI
from utils.settings import get_settings


def estimate_tokens(messages: Sequence[BaseMessage]) -> int:
    """Estimate message tokens locally, including tool calls and metadata."""
    return sum(
        (len(json.dumps(message.model_dump(), ensure_ascii=False, default=str)) + 2) // 3 + 4
        for message in messages
    )


def create_chat_model(
    *,
    temperature: float = 0,
    extra_body: dict[str, Any] | None = None,
) -> ChatOpenAI:
    """Create a ChatOpenAI client using centrally validated settings."""
    settings = get_settings()
    return ChatOpenAI(
        model=settings.agent_model,
        base_url=settings.openai_base_url,
        api_key=settings.openai_api_key,
        temperature=temperature,
        extra_body=extra_body,
    )
