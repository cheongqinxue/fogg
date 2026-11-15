"""User-scoped agent API (chat, layout, map actions)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from layout.models import (
    LayoutHead,
    LayoutHeadResponse,
    LayoutSyncRequest,
    LayoutSyncResponse,
)
from layout.service import sync_layout
from layout.store import get_layout_head, get_or_create_thread_layout
from layout.user_actions import UserActionRequest, UserActionResponse, handle_user_action
from api.messages.history import MessageHistoryResponse, list_ui_messages
from api.routes.chat_handlers import ChatRequest, chat_stream_response, run_chat_turn


def _require_user_id(user_id: str) -> str:
    cleaned = user_id.strip()
    if not cleaned:
        raise HTTPException(status_code=400, detail="user_id required")
    return cleaned


router = APIRouter(prefix="/users", tags=["users"])


@router.get("/{user_id}/messages", response_model=MessageHistoryResponse)
async def get_user_messages(
    user_id: str,
    cursor: str | None = Query(
        default=None, description="Opaque cursor for the next 50 older messages."
    ),
) -> MessageHistoryResponse:
    """Return the latest 50 persisted transcript messages, or an older page."""
    try:
        return await list_ui_messages(_require_user_id(user_id), cursor)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{user_id}/chat")
async def post_user_chat(user_id: str, body: ChatRequest) -> dict[str, Any]:
    """Run one agent turn (full graph until stop)."""
    return await run_chat_turn(_require_user_id(user_id), body)


@router.post("/{user_id}/chat/stream")
async def post_user_chat_stream(user_id: str, body: ChatRequest) -> StreamingResponse:
    """Stream LangGraph events as Server-Sent Events."""
    return chat_stream_response(_require_user_id(user_id), body)


@router.get("/{user_id}/layout", response_model=LayoutHeadResponse)
async def read_user_layout_head(
    user_id: str,
    revision: int | None = Query(default=None),
) -> LayoutHeadResponse:
    """Return server revision and hash (lightweight desync check)."""
    uid = _require_user_id(user_id)
    head = await get_layout_head(uid)
    if head is None:
        row = await get_or_create_thread_layout(uid)
        head = LayoutHead(revision=row.revision, layout_hash=row.layout_hash)
    matches = revision == head.revision if revision is not None else None
    return LayoutHeadResponse(
        revision=head.revision,
        layout_hash=head.layout_hash,
        client_revision_matches=matches,
    )


@router.post("/{user_id}/layout/sync", response_model=LayoutSyncResponse)
async def post_user_layout_sync(user_id: str, body: LayoutSyncRequest) -> LayoutSyncResponse:
    """Reconcile client layout deltas or full config with server state."""
    return await sync_layout(_require_user_id(user_id), body)


@router.post("/{user_id}/user-actions", response_model=UserActionResponse)
async def post_user_actions(user_id: str, body: UserActionRequest) -> UserActionResponse:
    """Record a user map gesture: layout head + checkpoint observation (no LLM turn)."""
    return await handle_user_action(_require_user_id(user_id), body)
