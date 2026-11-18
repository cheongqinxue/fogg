"""Offline tests for the loopback-only browser viewer."""

import asyncio
import importlib.util
from pathlib import Path

import pytest


@pytest.fixture
def viewer():
    path = Path(__file__).resolve().parents[2] / "scripts" / "watch-browser.py"
    spec = importlib.util.spec_from_file_location("browser_viewer", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Writer:
    def __init__(self):
        self.data = bytearray()

    def write(self, data):
        self.data.extend(data)

    async def drain(self):
        pass

    def close(self):
        pass

    async def wait_closed(self):
        pass


@pytest.mark.asyncio
async def test_live_frame_is_read_from_the_worker(viewer, monkeypatch):
    calls = []

    async def docker(*args):
        calls.append(args)
        return b"frame contents"

    monkeypatch.setattr(viewer, "docker", docker)
    session = "a" * 32
    reader, writer = asyncio.StreamReader(), Writer()
    reader.feed_data(f"GET /frame/{session} HTTP/1.1\r\nHost: 127.0.0.1:18083\r\n\r\n".encode())
    await viewer.handle(reader, writer, "worker-id")
    assert bytes(writer.data).endswith(b"frame contents")
    assert calls[0][-1] == f"/recordings/{session}/latest.png"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind,content_type", [("video", b"video/webm"), ("trace", b"application/zip")]
)
async def test_finished_session_exposes_playback_and_trace(viewer, monkeypatch, kind, content_type):
    async def docker(*_args):
        return b"recorded content"

    monkeypatch.setattr(viewer, "docker", docker)
    reader, writer = asyncio.StreamReader(), Writer()
    reader.feed_data(f"GET /{kind}/{'a' * 32} HTTP/1.1\r\nHost: localhost:18083\r\n\r\n".encode())
    await viewer.handle(reader, writer, "worker-id")
    assert content_type in writer.data
    assert bytes(writer.data).endswith(b"recorded content")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "host,path", [("attacker.test", "/"), ("localhost", "/frame/../../etc/passwd")]
)
async def test_viewer_rejects_external_hosts_and_path_traversal(viewer, monkeypatch, host, path):
    async def docker(*_args):
        pytest.fail("invalid requests must not execute Docker commands")

    monkeypatch.setattr(viewer, "docker", docker)
    reader, writer = asyncio.StreamReader(), Writer()
    reader.feed_data(f"GET {path} HTTP/1.1\r\nHost: {host}\r\n\r\n".encode())
    await viewer.handle(reader, writer, "worker-id")
    assert bytes(writer.data).startswith((b"HTTP/1.1 403", b"HTTP/1.1 404"))
