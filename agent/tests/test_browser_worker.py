"""Offline tests of browser-worker task isolation and cleanup."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from browser_agt.browser import PageObservation
from browser_agt import worker
from browser_agt.remote import RemoteBrowserRuntime


class FakeWriter:
    def __init__(self) -> None:
        self.output = bytearray()
        self.closed = False

    def write(self, data: bytes) -> None:
        self.output.extend(data)

    async def drain(self) -> None:
        pass

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        pass


class FakeJob:
    def __init__(self) -> None:
        self.url = ""

    async def navigate(self, url: str) -> None:
        self.url = url

    async def observe(self) -> PageObservation:
        return PageObservation(
            url=self.url,
            title="Page",
            text="Information",
            elements=(),
            screenshot=b"jpeg",
            scroll_target="element",
            scroll_top=350,
            scroll_height=1000,
            client_height=500,
            at_scroll_end=False,
            scroll_position_changed=True,
            screenshot_changed=True,
        )

    async def close(self) -> None:
        pass


class FakeRuntime:
    instances: list[FakeRuntime] = []

    def __init__(self, **kwargs: Any) -> None:
        self.options = kwargs
        self.job = FakeJob()
        self.closed = False
        self.instances.append(self)

    async def __aenter__(self) -> FakeRuntime:
        return self

    async def create_job(self) -> FakeJob:
        return self.job

    async def close(self) -> None:
        self.closed = True


def test_browser_identity_headers_are_selected_from_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        "BROWSER_ACCEPT_LANGUAGE",
        "BROWSER_DNT",
        "BROWSER_SEC_CH_UA",
        "BROWSER_SEC_CH_UA_MOBILE",
        "BROWSER_SEC_CH_UA_PLATFORM",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("BROWSER_ACCEPT_LANGUAGE", "en-US,en;q=0.9")
    monkeypatch.setenv("BROWSER_DNT", "1")
    monkeypatch.setenv("BROWSER_SEC_CH_UA", '"Chrome";v="155"')
    assert worker._browser_headers() == {
        "Accept-Language": "en-US,en;q=0.9",
        "DNT": "1",
        "sec-ch-ua": '"Chrome";v="155"',
    }


def test_browser_identity_rejects_header_injection(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BROWSER_ACCEPT_LANGUAGE", "en-US\r\nInjected: value")
    with pytest.raises(ValueError, match="newlines"):
        worker._browser_headers()


@pytest.mark.asyncio
async def test_worker_observes_page_and_cleans_up_on_disconnect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    FakeRuntime.instances.clear()
    monkeypatch.setattr(worker, "BrowserRuntime", FakeRuntime)
    reader = asyncio.StreamReader()
    for message in (
        {"op": "start"},
        {"op": "navigate", "url": "https://example.test/"},
        {"op": "observe"},
    ):
        reader.feed_data(json.dumps(message).encode() + b"\n")
    reader.feed_eof()
    writer = FakeWriter()

    await worker._handle_rpc(reader, writer)

    responses = [json.loads(line) for line in writer.output.splitlines()]
    assert all(response["ok"] for response in responses)
    assert responses[-1]["result"]["url"] == "https://example.test/"
    assert responses[-1]["result"]["screenshot"] == "anBlZw=="
    assert responses[-1]["result"]["scroll_target"] == "element"
    assert responses[-1]["result"]["scroll_position_changed"] is True
    assert responses[-1]["result"]["screenshot_changed"] is True
    assert FakeRuntime.instances[-1].closed
    assert FakeRuntime.instances[-1].options["proxy_server"] == "http://127.0.0.1:18882"
    assert FakeRuntime.instances[-1].options["headless"] is False
    assert FakeRuntime.instances[-1].options["browser_channel"] == "chrome"
    assert FakeRuntime.instances[-1].options["profile_dir"] == "/browser-profile"
    assert writer.closed


@pytest.mark.asyncio
async def test_worker_rejects_operations_before_start(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(worker, "BrowserRuntime", FakeRuntime)
    reader = asyncio.StreamReader()
    reader.feed_data(b'{"op":"navigate","url":"http://example.test/"}\n')
    reader.feed_eof()
    writer = FakeWriter()
    await worker._handle_rpc(reader, writer)
    assert json.loads(writer.output)["ok"] is False


@pytest.mark.asyncio
async def test_remote_runtime_closes_connection_when_start_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reader, writer = asyncio.StreamReader(), FakeWriter()
    reader.feed_data(b'{"ok":false,"error":"startup failed"}\n')
    reader.feed_eof()

    async def connect(_path: str, *, limit: int) -> tuple[asyncio.StreamReader, FakeWriter]:
        assert limit == worker.MAX_MESSAGE
        return reader, writer

    monkeypatch.setattr(asyncio, "open_unix_connection", connect)
    with pytest.raises(RuntimeError, match="startup failed"):
        async with RemoteBrowserRuntime():
            pytest.fail("worker startup must fail")
    assert writer.closed


@pytest.mark.asyncio
async def test_remote_observation_decodes_screenshot_bytes() -> None:
    reader, writer = asyncio.StreamReader(), FakeWriter()
    reader.feed_data(
        json.dumps(
            {
                "ok": True,
                "result": {
                    "url": "https://example.test/",
                    "title": "Example",
                    "text": "Visible page",
                    "elements": [],
                    "screenshot": "anBlZw==",
                    "scroll_target": "document",
                    "scroll_top": 420,
                    "scroll_height": 720,
                    "client_height": 720,
                    "at_scroll_end": True,
                    "scroll_position_changed": False,
                    "screenshot_changed": False,
                },
            }
        ).encode()
        + b"\n"
    )
    runtime = RemoteBrowserRuntime()
    runtime._reader = reader
    runtime._writer = writer
    job = await runtime.create_job()

    observation = await job.observe()

    assert observation.screenshot == b"jpeg"
    assert observation.at_scroll_end is True
    assert observation.scroll_position_changed is False
    assert observation.screenshot_changed is False
