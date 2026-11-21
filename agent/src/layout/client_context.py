"""Parse and format ``client_context`` from chat requests."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from layout.store import get_layout_head


class ClientContextPayload(BaseModel):
    """Body field the browser client sends on chat (schema v1)."""

    schema_version: int = Field(default=1, ge=1)
    revision: int = Field(ge=0)
    layout_hash: str
    sync_status: Literal["ok", "pending", "offline", "conflict"]
    viewport_summary: dict
    chat: dict[str, str] = Field(default_factory=lambda: {"mode": "preview"})
    capabilities: list[str] = Field(default_factory=lambda: ["map.set_viewport"])


def _viewport_line(viewport: dict) -> str:
    center = viewport.get("center") if isinstance(viewport.get("center"), dict) else {}
    lat = center.get("lat")
    lng = center.get("lng")
    zoom = viewport.get("zoom")
    label = viewport.get("label")
    coords = f"({lat}, {lng})" if lat is not None and lng is not None else "unknown"
    parts = [f"center={coords}"]
    if zoom is not None:
        parts.append(f"zoom={zoom}")
    if label:
        parts.append(f'label="{label}"')
    return ", ".join(parts)


async def format_client_context_digest(
    account_id: str, client_context: ClientContextPayload
) -> str:
    """Build a short system digest from client hint and server layout head.

    Args:
        account_id: Conversation key (for server layout lookup).
        client_context: Client-sent context snapshot.

    Returns:
        Plain-text digest for the model (not full layout JSON).
    """
    chat_mode = client_context.chat.get("mode", "preview")
    viewport_text = _viewport_line(client_context.viewport_summary)
    lines = [
        "Client context for this turn (hint only; authoritative layout is on the server):",
        f"- sync_status: {client_context.sync_status}",
        f"- client reports revision={client_context.revision}, layout_hash={client_context.layout_hash[:16]}…",
        f"- viewport: {viewport_text}",
        f"- chat UI mode: {chat_mode}",
        f"- UI capabilities: {', '.join(client_context.capabilities) or 'none'}",
    ]

    head = await get_layout_head(account_id)
    if head is None:
        lines.append("- server layout: not initialized yet (defaults apply on first sync)")
    else:
        hash_prefix = head.layout_hash[:16]
        lines.append(f"- server head: revision={head.revision}, layout_hash={hash_prefix}…")
        if client_context.revision != head.revision:
            lines.append(
                "- note: client revision differs from server — client may be stale or pending sync"
            )
        elif client_context.layout_hash != head.layout_hash:
            lines.append(
                "- note: same revision but hash differs — client cache may not match server layout"
            )

    sync_hints = {
        "ok": "Client believes layout is aligned.",
        "pending": "Client has local map/layout changes not yet acknowledged.",
        "offline": "Client could not sync; treat viewport as local-only.",
        "conflict": "Client is realigning after a rejected or failed sync.",
    }
    lines.append(
        f"- interpretation: {sync_hints.get(client_context.sync_status, client_context.sync_status)}",
    )

    return "\n".join(lines)
