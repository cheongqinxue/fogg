"""Shared helpers for configuring OpenAI-compatible chat models."""

from __future__ import annotations

import json
import os
from collections.abc import Sequence
from typing import Any

from langchain_core.messages import BaseMessage
from langchain_openai import ChatOpenAI


def estimate_tokens(messages: Sequence[BaseMessage]) -> int:
    """Estimate message tokens locally, including tool calls and metadata."""
    return sum(
        (len(json.dumps(message.model_dump(), ensure_ascii=False, default=str)) + 2) // 3 + 4
        for message in messages
    )


def create_chat_model(
    *,
    model_env: str,
    base_url_env: str,
    api_key_env: str,
    default_model: str,
    default_base_url: str,
    default_api_key: str = "ollama",
    temperature: float = 0,
    extra_body: dict[str, Any] | None = None,
) -> ChatOpenAI:
    """Create a ChatOpenAI client using configurable per-agent environment variables."""
    return ChatOpenAI(
        model=os.environ.get(model_env, default_model),
        base_url=os.environ.get(base_url_env, default_base_url),
        api_key=os.environ.get(api_key_env, default_api_key),
        temperature=temperature,
        extra_body=extra_body,
    )
