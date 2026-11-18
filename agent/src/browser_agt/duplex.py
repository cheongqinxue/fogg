"""Task-scoped message channel between the browser worker and its master."""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import uuid4


class BrowserMasterChannel:
    """Correlate browser messages with steering replies on one WebSocket task."""

    def __init__(self) -> None:
        self.outbound: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
        self._pending: dict[str, asyncio.Future[str]] = {}
        self._closed = False

    async def exchange(self, *, kind: str, payload: dict[str, Any]) -> str:
        """Send one browser update and wait for the master's steering response."""
        if self._closed:
            return "Continue with the research task."
        message_id = uuid4().hex
        future = asyncio.get_running_loop().create_future()
        self._pending[message_id] = future
        await self.outbound.put({"type": kind, "id": message_id, **payload})
        try:
            return await future
        finally:
            self._pending.pop(message_id, None)

    async def receive_steering(self, message: dict[str, Any]) -> bool:
        """Resolve a pending browser message; return false for unknown IDs."""
        message_id = message.get("id")
        future = self._pending.get(message_id) if isinstance(message_id, str) else None
        if future is None or future.done():
            return False
        instruction = message.get("instruction")
        future.set_result(instruction if isinstance(instruction, str) else "Continue.")
        return True

    async def close(self) -> None:
        """Unblock pending browser tools and stop the WebSocket sender."""
        if self._closed:
            return
        self._closed = True
        for future in self._pending.values():
            if not future.done():
                future.set_result("Continue with the research task.")
        await self.outbound.put(None)
