"""Tests for JSONL tool-call debugging records."""

from __future__ import annotations

import json

import pytest
from utils.request_context import request_account_id
from utils.tools import capture_tool_io


@pytest.mark.asyncio
async def test_capture_tool_io_records_async_inputs_output_and_request_id(tmp_path, monkeypatch):
    path = tmp_path / "debug" / "calls.jsonl"
    monkeypatch.setenv("AGENT_TOOL_IO_LOG_PATH", str(path))

    @capture_tool_io
    async def sample_tool(query: str, limit: int = 2) -> dict[str, object]:
        return {"query": query, "items": list(range(limit))}

    token = request_account_id.set("thread-123")
    try:
        assert await sample_tool("coffee") == {"query": "coffee", "items": [0, 1]}
    finally:
        request_account_id.reset(token)

    record = json.loads(path.read_text())
    assert record["tool"] == "sample_tool"
    assert record["caller"]["request_account_id"] == "thread-123"
    assert record["inputs"] == {"query": "coffee"}
    assert record["output"] == {"query": "coffee", "items": [0, 1]}
    assert record["error"] is None
    assert record["duration_ms"] >= 0
    assert path.stat().st_mode & 0o777 == 0o600


def test_capture_tool_io_records_exceptions_and_preserves_them(tmp_path, monkeypatch):
    path = tmp_path / "calls.jsonl"
    monkeypatch.setenv("AGENT_TOOL_IO_LOG_PATH", str(path))

    @capture_tool_io
    def failing_tool(value: int) -> None:
        raise ValueError("bad input")

    with pytest.raises(ValueError, match="bad input"):
        failing_tool(7)

    record = json.loads(path.read_text())
    assert record["caller"]["request_account_id"] is None
    assert record["inputs"] == {"value": 7}
    assert record["output"] is None
    assert record["error"] == {"type": "ValueError", "message": "bad input"}
