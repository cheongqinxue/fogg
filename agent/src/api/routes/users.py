"""User-scoped agent API (chat and layout)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from layout.models import (
    LayoutHead,
    LayoutHeadResponse,
    LayoutSyncRequest,
    LayoutSyncResponse,
)
from layout.service import sync_layout
from layout.store import get_layout_head, get_or_create_user_layout
from utils.checkpointing import get_checkpointer

from api.auth import authenticated_account_id, require_path_account_id
from api.messages.history import (
    ClearHistoryResponse,
    MessageHistoryResponse,
    clear_ui_history,
    list_ui_messages,
)
from api.routes.chat_handlers import ChatRequest, chat_stream_response, run_chat_turn

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/{account_id}/messages", response_model=MessageHistoryResponse)
async def get_user_messages(
    account_id: str,
    verified_account_id: str = Depends(authenticated_account_id),
    cursor: str | None = Query(
        default=None, description="Opaque cursor for the next 50 older messages."
    ),
) -> MessageHistoryResponse:
    """Return the latest 50 persisted transcript messages, or an older page."""
    try:
        return await list_ui_messages(
            require_path_account_id(account_id, verified_account_id), cursor
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/{account_id}/messages", response_model=ClearHistoryResponse)
async def delete_user_messages(
    account_id: str,
    verified_account_id: str = Depends(authenticated_account_id),
) -> ClearHistoryResponse:
    """Clear transcript and LangGraph history while preserving the saved layout."""
    return await clear_ui_history(
        require_path_account_id(account_id, verified_account_id), get_checkpointer()
    )


@router.post("/{account_id}/chat")
async def post_user_chat(
    account_id: str,
    body: ChatRequest,
    verified_account_id: str = Depends(authenticated_account_id),
) -> dict[str, Any]:
    """Run one agent turn (full graph until stop)."""
    return await run_chat_turn(require_path_account_id(account_id, verified_account_id), body)


@router.post("/{account_id}/chat/stream")
async def post_user_chat_stream(
    account_id: str,
    body: ChatRequest,
    verified_account_id: str = Depends(authenticated_account_id),
) -> StreamingResponse:
    """Stream LangGraph events as Server-Sent Events."""
    return chat_stream_response(require_path_account_id(account_id, verified_account_id), body)


@router.get("/{account_id}/layout", response_model=LayoutHeadResponse)
async def read_user_layout_head(
    account_id: str,
    verified_account_id: str = Depends(authenticated_account_id),
    revision: int | None = Query(default=None),
) -> LayoutHeadResponse:
    """Return server revision and hash (lightweight desync check)."""
    account_id = require_path_account_id(account_id, verified_account_id)
    head = await get_layout_head(account_id)
    if head is None:
        row = await get_or_create_user_layout(account_id)
        head = LayoutHead(revision=row.revision, layout_hash=row.layout_hash)
    matches = revision == head.revision if revision is not None else None
    return LayoutHeadResponse(
        revision=head.revision,
        layout_hash=head.layout_hash,
        client_revision_matches=matches,
    )


@router.post("/{account_id}/layout/sync", response_model=LayoutSyncResponse)
async def post_user_layout_sync(
    account_id: str,
    body: LayoutSyncRequest,
    verified_account_id: str = Depends(authenticated_account_id),
) -> LayoutSyncResponse:
    """Reconcile client layout deltas or full config with server state."""
    return await sync_layout(require_path_account_id(account_id, verified_account_id), body)
