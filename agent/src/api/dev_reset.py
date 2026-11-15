"""Dev-only reset of layout rows and LangGraph checkpoint threads."""

from __future__ import annotations

import os

from pydantic import BaseModel, Field

from graph.checkpointing import get_checkpointer
from layout.store import (
    _require_pool,
    delete_thread_layout,
    truncate_all_thread_layouts,
)
from api.messages.store import delete_thread_messages, truncate_messages


class DevResetRequest(BaseModel):
    """Reset scope for local testing."""

    user_id: str | None = Field(
        default=None,
        description="Clear this user only. Omit or null to reset **all** users (nuclear).",
    )


class DevResetResponse(BaseModel):
    """Summary of what was cleared."""

    scope: str
    layout_rows_removed: int
    transcript_messages_removed: int
    checkpoint_threads_cleared: str


def dev_reset_enabled() -> bool:
    """Return whether dev reset routes are allowed."""
    raw = os.environ.get("AGENT_DEV_RESET_ENABLED", "false").strip().lower()
    return raw in {"1", "true", "yes", "on"}


async def reset_agent_state(body: DevResetRequest) -> DevResetResponse:
    """Delete layout and checkpoint data for one user or for every user."""
    checkpointer = get_checkpointer()
    if body.user_id is not None:
        user_id = body.user_id.strip()
        if not user_id:
            msg = "user_id must be non-empty when provided"
            raise ValueError(msg)
        layout_removed = await delete_thread_layout(user_id)
        transcript_removed = await delete_thread_messages(user_id)
        await checkpointer.adelete_thread(user_id)
        return DevResetResponse(
            scope=f"user:{user_id}",
            layout_rows_removed=layout_removed,
            transcript_messages_removed=transcript_removed,
            checkpoint_threads_cleared=user_id,
        )

    layout_removed = await truncate_all_thread_layouts()
    transcript_removed = await truncate_messages()
    pool = _require_pool()
    async with pool.connection() as conn:
        await conn.execute(
            "TRUNCATE TABLE checkpoint_writes, checkpoint_blobs, checkpoints",
        )
        await conn.commit()
    return DevResetResponse(
        scope="all",
        layout_rows_removed=layout_removed,
        transcript_messages_removed=transcript_removed,
        checkpoint_threads_cleared="all",
    )
