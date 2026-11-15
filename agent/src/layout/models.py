"""Pydantic models for layout schema v1 and sync payloads."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class LayoutDocument(BaseModel):
    """Layout document schema v1."""

    schema_version: Literal[1] = 1
    map: dict[str, Any]
    chrome: dict[str, Any] = Field(default_factory=lambda: {"chat": {"mode": "preview"}})
    workspace: dict[str, Any] = Field(default_factory=lambda: {"slots": []})

    @classmethod
    def default_singapore(cls) -> LayoutDocument:
        """Default framing aligned with the browser map's Singapore viewport."""
        return cls(
            map={
                "viewport": {
                    "center": {"lat": 1.3521, "lng": 103.8198},
                    "zoom": 11.5,
                },
            },
        )

    def to_storage_dict(self) -> dict[str, Any]:
        """JSON-serializable dict for persistence and hashing."""
        return self.model_dump(mode="json", exclude_none=True)

    @field_validator("map")
    @classmethod
    def _map_has_viewport(cls, value: dict[str, Any]) -> dict[str, Any]:
        viewport = value.get("viewport")
        if not isinstance(viewport, dict):
            msg = "layout.map.viewport is required"
            raise ValueError(msg)
        return value


class LayoutHead(BaseModel):
    """Revision and hash without full document."""

    revision: int
    layout_hash: str


class LayoutHeadResponse(LayoutHead):
    """GET layout head; optional client revision check from query param."""

    client_revision_matches: bool | None = Field(
        default=None,
        description="Present when the client sends ``?revision=`` for a quick stale check.",
    )


class LayoutSyncResponse(BaseModel):
    """Response for layout sync and related routes."""

    accepted: bool
    revision: int
    layout_hash: str
    layout: dict[str, Any]
    reject_reason: str | None = None


class ProposedDelta(BaseModel):
    """Client-proposed layout mutation."""

    op: Literal["map.set_viewport"]
    source: Literal["user", "agent"]
    payload: dict[str, Any]


class AppliedAck(BaseModel):
    """Client ack after applying ``client_command``."""

    command_id: str
    ok: bool
    error: str | None = None


class LayoutSyncRequest(BaseModel):
    """``POST …/layout/sync`` body."""

    client_revision: int
    sync_mode: Literal["full"] | None = None
    proposed_delta: ProposedDelta | None = None
    applied: AppliedAck | None = None
    layout: dict[str, Any] | None = None
    layout_hash: str | None = None
    last_error: str | None = None
    pending_deltas: list[Any] | None = None
