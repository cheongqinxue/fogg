"""map_set_viewport tool and client_command SSE mapping."""

from __future__ import annotations

import json
import os
import uuid

import pytest

from layout._tool import (
    client_command_from_tool_output,
    execute_map_set_viewport_tool,
)
from layout.store import get_or_create_thread_layout, init_layout_store, shutdown_layout_store


class TestMapSetViewport:
    @pytest.mark.unit
    def test_client_command_from_ok_tool_output(self) -> None:
        output = json.dumps(
            {
                "status": "ok",
                "command_id": "abc123",
                "base_revision": 2,
                "payload": {"center": {"lat": 1.0, "lng": 2.0}, "zoom": 10},
            },
        )
        cmd = client_command_from_tool_output("map_set_viewport", output, run_id="run-1")
        assert cmd is not None
        assert cmd["type"] == "client_command"
        assert cmd["command"] == "map.set_viewport"
        assert cmd["command_id"] == "abc123"
        assert cmd["source"]["run_id"] == "run-1"

    @pytest.mark.unit
    def test_no_client_command_when_unchanged(self) -> None:
        output = json.dumps({"status": "unchanged"})
        assert client_command_from_tool_output("map_set_viewport", output, run_id=None) is None

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_apply_updates_layout_and_returns_command(self) -> None:
        if not (os.environ.get("AGENT_DATABASE_URL") or os.environ.get("DATABASE_URL")):
            pytest.skip("DATABASE_URL not set")
        await init_layout_store()
        thread_id = f"pytest-mv-{uuid.uuid4()}"
        try:
            await get_or_create_thread_layout(thread_id)
            raw = await execute_map_set_viewport_tool(
                thread_id,
                lat=35.68,
                lng=139.76,
                zoom=9,
            )
            data = json.loads(raw)
            assert data["status"] == "ok"
            assert data["base_revision"] == 0
            assert data["layout_revision"] == 1
            cmd = client_command_from_tool_output("map_set_viewport", raw, run_id="r")
            assert cmd is not None
            assert cmd["payload"]["zoom"] == 9

            again = await execute_map_set_viewport_tool(thread_id, lat=35.68, lng=139.76, zoom=9)
            assert json.loads(again)["status"] == "unchanged"
        finally:
            await shutdown_layout_store()
