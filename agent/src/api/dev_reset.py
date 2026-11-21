"""Dev-only reset of layout rows and LangGraph checkpoint threads."""

from __future__ import annotations

from layout.store import (
    delete_user_layout,
    truncate_all_user_layouts,
)
from pydantic import BaseModel, Field
from utils.checkpointing import checkpoint_thread_id, clear_all_checkpoint_threads, get_checkpointer
from utils.settings import get_settings

from api.messages.store import delete_user_messages, truncate_messages


class DevResetRequest(BaseModel):
    """Reset scope for local testing."""

    account_id: str | None = Field(
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
    return get_settings().agent_dev_reset_enabled


async def reset_agent_state(body: DevResetRequest) -> DevResetResponse:
    """Delete layout and checkpoint data for one user or for every user."""
    checkpointer = get_checkpointer()
    if body.account_id is not None:
        account_id = body.account_id.strip()
        if not account_id:
            msg = "account_id must be non-empty when provided"
            raise ValueError(msg)
        layout_removed = await delete_user_layout(account_id)
        transcript_removed = await delete_user_messages(account_id)
        thread_id = await checkpoint_thread_id(account_id)
        await checkpointer.adelete_thread(thread_id)
        return DevResetResponse(
            scope=f"account:{account_id}",
            layout_rows_removed=layout_removed,
            transcript_messages_removed=transcript_removed,
            checkpoint_threads_cleared=thread_id,
        )

    layout_removed = await truncate_all_user_layouts()
    transcript_removed = await truncate_messages()
    await clear_all_checkpoint_threads()
    return DevResetResponse(
        scope="all",
        layout_rows_removed=layout_removed,
        transcript_messages_removed=transcript_removed,
        checkpoint_threads_cleared="all",
    )
