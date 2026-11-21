"""Paginated read API for the durable, UI-facing conversation transcript."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel

from api.messages.store import (
    decode_cursor,
    delete_thread_messages,
    encode_cursor,
    list_messages,
)


class UiMessage(BaseModel):
    """One persisted line in the dialogue transcript."""

    id: str
    role: Literal["user", "assistant"]
    text: str
    timestamp: datetime


class MessageHistoryResponse(BaseModel):
    """One page, in display order from oldest to newest."""

    messages: list[UiMessage]
    has_more: bool
    next_cursor: str | None


class ClearHistoryResponse(BaseModel):
    """Result of clearing chat and checkpoint history while preserving layout."""

    cleared: bool
    transcript_messages_removed: int
    layout_preserved: bool = True


async def list_ui_messages(user_id: str, cursor: str | None = None) -> MessageHistoryResponse:
    """Return up to 50 persisted messages, newest page by default.

    ``cursor`` points to the oldest message in the preceding page. The next
    page contains IDs strictly older than that message. Each page is returned
    oldest → newest for direct transcript rendering.
    """
    before_id = decode_cursor(cursor) if cursor is not None else None
    rows, has_more = await list_messages(user_id, before_id)
    messages = [
        UiMessage(
            id=str(row["id"]),
            role=row["role"],
            text=row["text"],
            timestamp=row["created_at"],
        )
        for row in rows
    ]
    next_cursor = encode_cursor(int(rows[0]["id"])) if has_more and rows else None
    return MessageHistoryResponse(messages=messages, has_more=has_more, next_cursor=next_cursor)


async def clear_ui_history(thread_id: str, checkpointer: Any) -> ClearHistoryResponse:
    """Clear a user's LangGraph thread and UI transcript, leaving layout intact."""
    await checkpointer.adelete_thread(thread_id)
    removed = await delete_thread_messages(thread_id)
    return ClearHistoryResponse(cleared=True, transcript_messages_removed=removed)
