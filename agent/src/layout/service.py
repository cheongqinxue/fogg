"""Layout sync business rules."""

from __future__ import annotations

import logging

from pydantic import ValidationError

from layout.models import LayoutDocument, LayoutSyncRequest, LayoutSyncResponse, ProposedDelta
from layout.store import ThreadLayoutRow, get_or_create_thread_layout, upsert_thread_layout

logger = logging.getLogger(__name__)


def _response_from_row(
    row: ThreadLayoutRow, *, accepted: bool, reject_reason: str | None
) -> LayoutSyncResponse:
    return LayoutSyncResponse(
        accepted=accepted,
        revision=row.revision,
        layout_hash=row.layout_hash,
        layout=row.layout,
        reject_reason=reject_reason,
    )


def _apply_viewport_delta(layout: dict, payload: dict) -> dict:
    """Merge ``map.set_viewport`` payload into a layout document dict."""
    center = payload.get("center") or {}
    if not isinstance(center, dict):
        msg = "viewport payload missing center"
        raise ValueError(msg)
    lat = center.get("lat")
    lng = center.get("lng")
    if lat is None or lng is None:
        msg = "viewport center requires lat and lng"
        raise ValueError(msg)
    zoom = payload.get("zoom")
    if zoom is None:
        viewport = layout.get("map", {}).get("viewport", {})
        zoom = viewport.get("zoom", 11.5)
    viewport: dict = {
        "center": {"lat": float(lat), "lng": float(lng)},
        "zoom": float(zoom),
    }
    label = payload.get("label")
    if label is not None:
        viewport["label"] = label
    elif "label" in layout.get("map", {}).get("viewport", {}):
        old_label = layout["map"]["viewport"].get("label")
        if old_label is not None:
            viewport["label"] = old_label
    updated = dict(layout)
    updated.setdefault("map", {})["viewport"] = viewport
    return updated


def _validate_layout(raw: dict) -> dict:
    """Parse and re-serialize layout v1 for canonical storage."""
    try:
        return LayoutDocument.model_validate(raw).to_storage_dict()
    except ValidationError as exc:
        msg = f"invalid layout document: {exc.errors()[0]['msg']}"
        raise ValueError(msg) from exc


async def sync_layout(thread_id: str, request: LayoutSyncRequest) -> LayoutSyncResponse:
    """Apply a client sync request and return the authoritative layout head."""
    row = await get_or_create_thread_layout(thread_id)

    if request.client_revision != row.revision:
        return _response_from_row(
            row,
            accepted=False,
            reject_reason="stale_revision",
        )

    if request.pending_deltas:
        return _response_from_row(
            row,
            accepted=False,
            reject_reason="pending_deltas_not_supported",
        )

    try:
        if request.sync_mode == "full":
            if request.layout is None:
                return _response_from_row(
                    row,
                    accepted=False,
                    reject_reason="full_sync_requires_layout",
                )
            layout = _validate_layout(request.layout)
            new_revision = row.revision + 1
            row = await upsert_thread_layout(thread_id, new_revision, layout)
            return _response_from_row(row, accepted=True, reject_reason=None)

        if request.proposed_delta is not None:
            delta = request.proposed_delta
            if delta.op != "map.set_viewport":
                return _response_from_row(
                    row,
                    accepted=False,
                    reject_reason="unsupported_delta_op",
                )
            layout = _apply_viewport_delta(row.layout, delta.payload)
            layout = _validate_layout(layout)
            new_revision = row.revision + 1
            row = await upsert_thread_layout(thread_id, new_revision, layout)
            return _response_from_row(row, accepted=True, reject_reason=None)

        if request.applied is not None:
            # Monotonic revision even when layout JSON is unchanged (client command ack).
            new_revision = row.revision + 1
            row = await upsert_thread_layout(thread_id, new_revision, row.layout)
            return _response_from_row(row, accepted=True, reject_reason=None)

        return _response_from_row(
            row,
            accepted=False,
            reject_reason="empty_sync_body",
        )
    except ValueError as exc:
        logger.info("Layout sync rejected for thread %s: %s", thread_id, exc)
        return _response_from_row(row, accepted=False, reject_reason=str(exc))


async def sync_user_viewport_layout(
    thread_id: str,
    *,
    client_revision: int,
    payload: dict,
) -> LayoutSyncResponse:
    """Update layout from a user viewport payload (``user-actions`` / pan)."""
    request = LayoutSyncRequest(
        client_revision=client_revision,
        proposed_delta=ProposedDelta(
            op="map.set_viewport",
            source="user",
            payload=payload,
        ),
    )
    return await sync_layout(thread_id, request)
