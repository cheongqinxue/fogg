"""Unix socket client implementing the BrowserRuntime interface for research service."""

from __future__ import annotations

import asyncio
import base64
from functools import partial
import json
import os
from collections.abc import Awaitable, Callable
from typing import Any

from browser_agt.browser import BrowserPolicyError, ObservedElement, PageObservation

MAX_MESSAGE = 1_500_000


class RemoteBrowserRuntime:
    """One worker connection per task; disconnecting always destroys its browser context."""

    def __init__(
        self,
        socket_path: str | None = None,
        *,
        timeout_seconds: float = 100,
        connection_factory: Callable[
            ..., Awaitable[tuple[asyncio.StreamReader, asyncio.StreamWriter]]
        ]
        | None = None,
    ) -> None:
        self.socket_path = socket_path or os.environ.get(
            "BROWSER_WORKER_SOCKET", "/run/fogg-browser/worker.sock"
        )
        self.timeout_seconds = timeout_seconds
        self._connection_factory = connection_factory or partial(
            asyncio.open_unix_connection, limit=MAX_MESSAGE
        )
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._job: RemoteBrowserJob | None = None
        self._lock = asyncio.Lock()

    async def __aenter__(self) -> RemoteBrowserRuntime:
        if self._writer is not None:
            raise RuntimeError("remote browser runtime already started")
        self._reader, self._writer = await asyncio.wait_for(
            self._connection_factory(self.socket_path), timeout=5
        )
        try:
            result = await self._call("start")
            if result == {"started": True}:
                return self
        except BaseException:
            await self.close()
            raise
        await self.close()
        raise RuntimeError("browser worker returned an invalid start response")

    async def __aexit__(self, *_: Any) -> None:
        await self.close()

    async def create_job(self) -> RemoteBrowserJob:
        if self._writer is None:
            raise RuntimeError("use RemoteBrowserRuntime as an async context manager")
        if self._job is None:
            self._job = RemoteBrowserJob(self)
        return self._job

    async def _call(self, op: str, **fields: Any) -> Any:
        if self._writer is None or self._reader is None:
            raise RuntimeError("browser worker connection is closed")
        async with self._lock:
            line = json.dumps({"op": op, **fields}, separators=(",", ":")).encode() + b"\n"
            if len(line) > MAX_MESSAGE:
                raise BrowserPolicyError("browser worker request is too large")
            self._writer.write(line)
            await asyncio.wait_for(self._writer.drain(), timeout=5)
            response = await asyncio.wait_for(self._reader.readline(), timeout=self.timeout_seconds)
            if not response or len(response) > MAX_MESSAGE:
                raise RuntimeError("browser worker closed or exceeded response limit")
            decoded = json.loads(response)
            if not decoded.get("ok"):
                if decoded.get("policy"):
                    raise BrowserPolicyError(decoded.get("error", "browser action blocked"))
                raise RuntimeError(decoded.get("error", "browser worker operation failed"))
            return decoded.get("result")

    async def close(self) -> None:
        writer, self._writer = self._writer, None
        self._reader = None
        self._job = None
        if writer is not None:
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass


class RemoteBrowserJob:
    def __init__(self, runtime: RemoteBrowserRuntime) -> None:
        self._runtime = runtime
        self._closed = False

    async def navigate(self, url: str) -> None:
        await self._runtime._call("navigate", url=url)

    async def observe(self) -> PageObservation:
        result = await self._runtime._call("observe")
        return PageObservation(
            url=result["url"],
            title=result["title"],
            text=result["text"],
            elements=tuple(ObservedElement(**element) for element in result["elements"]),
            screenshot=(
                base64.b64decode(result["screenshot"], validate=True)
                if result.get("screenshot")
                else None
            ),
            scroll_target=result.get("scroll_target", "document"),
            scroll_top=float(result.get("scroll_top", 0)),
            scroll_height=float(result.get("scroll_height", 0)),
            client_height=float(result.get("client_height", 0)),
            at_scroll_end=bool(result.get("at_scroll_end", False)),
            scroll_position_changed=result.get("scroll_position_changed"),
            screenshot_changed=result.get("screenshot_changed"),
        )

    async def click(self, element_id: str) -> None:
        await self._runtime._call("click", element_id=element_id)

    async def fill(self, element_id: str, value: str) -> None:
        await self._runtime._call("fill", element_id=element_id, value=value)

    async def click_at(self, x: int, y: int) -> None:
        await self._runtime._call("click_at", x=x, y=y)

    async def type_text(self, value: str) -> None:
        await self._runtime._call("type_text", value=value)

    async def press_hotkey(self, key: str) -> None:
        await self._runtime._call("hotkey", key=key)

    async def scroll_at(self, x: int, y: int, direction: str) -> None:
        await self._runtime._call("scroll_at", x=x, y=y, direction=direction)

    async def wait(self, seconds: float = 2) -> None:
        await self._runtime._call("wait", seconds=seconds)

    async def back(self) -> None:
        await self._runtime._call("back")

    async def close(self) -> None:
        if not self._closed and self._runtime._writer is not None:
            self._closed = True
            await self._runtime._call("close")
