"""User product actions (map pan) — layout head + checkpoint observations."""

from __future__ import annotations

import copy
import logging
from typing import Any, Literal

from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field, field_validator

from master_agt.agent import get_graph
from layout.models import LayoutSyncResponse
from layout.service import sync_user_viewport_layout
from layout.store import get_or_create_thread_layout, upsert_thread_layout

logger = logging.getLogger(__name__)


class UserActionRequest(BaseModel):
    """``POST …/user-actions`` body (v1)."""

    action: Literal["map.viewport_changed"]
    occurred_at: str = Field(min_length=1)
    client_revision: int = Field(ge=0)
    payload: dict[str, Any]

    @field_validator("payload")
    @classmethod
    def _payload_has_viewport(cls, value: dict[str, Any]) -> dict[str, Any]:
        center = value.get("center")
        if not isinstance(center, dict):
            msg = "payload.center is required"
            raise ValueError(msg)
        if center.get("lat") is None or center.get("lng") is None:
            msg = "payload.center.lat and .lng are required"
            raise ValueError(msg)
        return value


class UserActionResponse(BaseModel):
    """``POST …/user-actions`` response."""

    accepted: bool
    revision: int
    layout_hash: str
    reject_reason: str | None = None


def _observation_text(
    *,
    action: str,
    occurred_at: str,
    payload: dict[str, Any],
    client_revision: int,
    server_revision: int,
) -> str:
    center = payload.get("center") or {}
    lat = center.get("lat")
    lng = center.get("lng")
    zoom = payload.get("zoom")
    return (
        f"Map action ({action}) at {occurred_at}: "
        f"center=({lat}, {lng}) zoom={zoom}. "
        f"Client revision was {client_revision}; server revision now {server_revision}."
    )


async def _append_observation(thread_id: str, content: str, action: str) -> None:
    """Append a non-chat observation to the checkpointed thread."""
    graph = get_graph()
    config = {"configurable": {"thread_id": thread_id}}
    message = HumanMessage(
        content=content,
        additional_kwargs={"kind": "user_action", "action": action},
    )
    await graph.aupdate_state(config, {"messages": [message]})


async def handle_user_action(thread_id: str, body: UserActionRequest) -> UserActionResponse:
    """Apply layout update and record an observation when accepted.

    Args:
        thread_id: LangGraph / layout key.
        body: Validated user action request.

    Returns:
        Head revision and hash (no full layout document).
    """
    before_row = await get_or_create_thread_layout(thread_id)
    previous_revision = before_row.revision
    previous_layout = copy.deepcopy(before_row.layout)

    layout_result: LayoutSyncResponse = await sync_user_viewport_layout(
        thread_id,
        client_revision=body.client_revision,
        payload=body.payload,
    )
    if not layout_result.accepted:
        return UserActionResponse(
            accepted=False,
            revision=layout_result.revision,
            layout_hash=layout_result.layout_hash,
            reject_reason=layout_result.reject_reason,
        )

    text = _observation_text(
        action=body.action,
        occurred_at=body.occurred_at,
        payload=body.payload,
        client_revision=body.client_revision,
        server_revision=layout_result.revision,
    )
    try:
        await _append_observation(thread_id, text, body.action)
    except Exception:
        logger.exception(
            "Checkpoint observation failed for thread %s — rolling back layout revision",
            thread_id,
        )
        rolled_back = await upsert_thread_layout(thread_id, previous_revision, previous_layout)
        return UserActionResponse(
            accepted=False,
            revision=rolled_back.revision,
            layout_hash=rolled_back.layout_hash,
            reject_reason="checkpoint_failed",
        )

    return UserActionResponse(
        accepted=True,
        revision=layout_result.revision,
        layout_hash=layout_result.layout_hash,
        reject_reason=None,
    )
