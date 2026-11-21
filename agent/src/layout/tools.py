"""Tool schemas and implementations owned by this functionality module."""

from __future__ import annotations

import json
import uuid
from typing import Any

from langchain_core.tools import tool
from pydantic import Field
from utils.request_context import request_user_id
from utils.tools import PrioritizedToolInput, capture_tool_io
from layout.models import LayoutSyncRequest, ProposedDelta
from layout.service import sync_layout
from layout.store import get_or_create_thread_layout


class MapSetViewportInput(PrioritizedToolInput):
    lat: float = Field(ge=-90, le=90, description="Target map center latitude in WGS84 degrees.")
    lng: float = Field(ge=-180, le=180, description="Target map center longitude in WGS84 degrees.")
    zoom: float | None = Field(
        default=None,
        ge=0,
        le=22,
        description="Optional map zoom; omit to preserve current zoom when reasonable.",
    )
    label: str | None = Field(
        default=None, description="Short human-readable label for the new map focus."
    )


def _viewport_payload(lat: float, lng: float, zoom: float, label: str | None) -> dict[str, Any]:
    viewport: dict[str, Any] = {
        "center": {"lat": lat, "lng": lng},
        "zoom": zoom,
    }
    if label is not None:
        viewport["label"] = label
    return viewport


def _viewport_matches(
    layout: dict[str, Any], lat: float, lng: float, zoom: float, *, eps: float = 1e-5
) -> bool:
    viewport = layout.get("map", {}).get("viewport", {})
    center = viewport.get("center") or {}
    try:
        cur_lat = float(center.get("lat"))
        cur_lng = float(center.get("lng"))
        cur_zoom = float(viewport.get("zoom"))
    except (TypeError, ValueError):
        return False
    return abs(cur_lat - lat) < eps and abs(cur_lng - lng) < eps and abs(cur_zoom - zoom) < eps


async def execute_map_set_viewport_tool(
    thread_id: str,
    *,
    lat: float,
    lng: float,
    zoom: float | None = None,
    label: str | None = None,
) -> str:
    """Update server layout and return JSON for the tool + SSE ``client_command``.

    Args:
        thread_id: Layout / checkpoint key.
        lat: Target latitude (WGS84).
        lng: Target longitude (WGS84).
        zoom: Map zoom; keeps current server zoom when omitted.
        label: Optional map label.

    Returns:
        JSON string with ``status``, optional ``command_id``, ``base_revision``, ``payload``.
    """
    row = await get_or_create_thread_layout(thread_id)
    current_viewport = row.layout.get("map", {}).get("viewport", {})
    target_zoom = float(zoom if zoom is not None else current_viewport.get("zoom", 11.5))
    if _viewport_matches(row.layout, lat, lng, target_zoom):
        return json.dumps(
            {
                "status": "unchanged",
                "message": "Viewport already matches; no client_command emitted.",
            },
        )

    viewport_payload = _viewport_payload(lat, lng, target_zoom, label)
    base_revision = row.revision
    layout_result = await sync_layout(
        thread_id,
        LayoutSyncRequest(
            client_revision=base_revision,
            proposed_delta=ProposedDelta(
                op="map.set_viewport",
                source="agent",
                payload=viewport_payload,
            ),
        ),
    )
    if not layout_result.accepted:
        return json.dumps(
            {
                "status": "error",
                "message": layout_result.reject_reason or "layout rejected",
            },
        )

    command_id = uuid.uuid4().hex
    return json.dumps(
        {
            "status": "ok",
            "command_id": command_id,
            "base_revision": base_revision,
            "payload": viewport_payload,
            "layout_revision": layout_result.revision,
            "layout_hash": layout_result.layout_hash,
            "message": f"Requested map focus at ({lat}, {lng}) zoom {target_zoom}.",
        },
    )


@tool(args_schema=MapSetViewportInput)
@capture_tool_io
async def map_set_viewport(
    lat: float, lng: float, zoom: float | None = None, label: str | None = None
) -> str:
    """Move the client map to a useful center and optional zoom."""
    return await execute_map_set_viewport_tool(
        request_user_id.get(), lat=lat, lng=lng, zoom=zoom, label=label
    )
