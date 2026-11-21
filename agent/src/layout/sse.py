"""Format layout tool outputs as client command SSE events."""

from __future__ import annotations

import json
from typing import Any


_TOOL_NAME = "map_set_viewport"


def client_command_from_tool_output(
    tool_name: str | None,
    output: Any,
    *,
    run_id: str | None,
) -> dict[str, Any] | None:
    """Build SSE ``client_command`` payload from a tool result, if applicable."""
    if tool_name != _TOOL_NAME:
        return None
    text = output
    if not isinstance(text, str):
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    if data.get("status") != "ok":
        return None
    return {
        "type": "client_command",
        "command_id": data["command_id"],
        "base_revision": data["base_revision"],
        "command": "map.set_viewport",
        "payload": data["payload"],
        "source": {"tool": _TOOL_NAME, "run_id": run_id},
    }
