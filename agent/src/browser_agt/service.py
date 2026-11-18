"""Private WebSocket service for bounded, supervised browser research tasks."""

from __future__ import annotations

import asyncio
import hmac
import os
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from opentelemetry import context, propagate

from browser_agt.agent import research
from agent_utils.tracing import init_tracing, shutdown_tracing
from browser_agt.agent import ResearchRequest, ResearchResult
from browser_agt.duplex import BrowserMasterChannel


def _bounded_float(name: str, default: float, maximum: float) -> float:
    try:
        value = float(os.environ.get(name, str(default)))
    except ValueError:
        value = default
    return max(1.0, min(value, maximum))


try:
    _MAX_CONCURRENT_TASKS = max(
        1, min(int(os.environ.get("BROWSER_AGENT_MAX_CONCURRENT_TASKS", "1")), 16)
    )
except ValueError:
    _MAX_CONCURRENT_TASKS = 1
_TASK_TIMEOUT_SECONDS = _bounded_float("BROWSER_AGENT_TASK_TIMEOUT_SECONDS", 300, 300)
_slots = asyncio.Semaphore(_MAX_CONCURRENT_TASKS)


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    init_tracing()
    try:
        yield
    finally:
        await shutdown_tracing()


app = FastAPI(title="FOGG browser research service", version="0.1.0", lifespan=_lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    """Liveness only; does not expose credentials or model configuration."""
    return {"status": "ok"}


@app.websocket("/duplex")
async def duplex_endpoint(websocket: WebSocket) -> None:
    """Run one authenticated research task over a bidirectional message channel."""
    expected = os.environ.get("BROWSER_AGENT_SERVICE_TOKEN", "").strip()
    authorization = websocket.headers.get("authorization", "")
    supplied = authorization[len("Bearer ") :] if authorization.startswith("Bearer ") else ""
    if not expected or not hmac.compare_digest(supplied, expected):
        await websocket.close(code=4401, reason="Unauthorized")
        return
    if _slots.locked():
        await websocket.close(code=4429, reason="Research capacity is full")
        return
    await _slots.acquire()
    channel = BrowserMasterChannel()
    research_task: asyncio.Task[ResearchResult] | None = None
    sender: asyncio.Task[None] | None = None
    receiver: asyncio.Task[dict[str, Any]] | None = None
    trace_token = context.attach(propagate.extract(dict(websocket.headers)))
    try:
        await websocket.accept()
        start = await websocket.receive_json()
        if not isinstance(start, dict) or start.get("type") != "start":
            await websocket.close(code=4400, reason="Expected start message")
            return
        try:
            request = ResearchRequest.model_validate(start.get("request", {}))
        except Exception:
            await websocket.close(code=4400, reason="Invalid research request")
            return

        async def send_messages() -> None:
            while True:
                message = await channel.outbound.get()
                if message is None:
                    return
                await websocket.send_json(message)

        research_task = asyncio.create_task(
            research(request, timeout_seconds=_TASK_TIMEOUT_SECONDS, master_channel=channel)
        )
        sender = asyncio.create_task(send_messages())
        receiver = asyncio.create_task(websocket.receive_json())
        while not research_task.done():
            done, _ = await asyncio.wait(
                {research_task, receiver}, return_when=asyncio.FIRST_COMPLETED
            )
            if receiver in done:
                message = receiver.result()
                if isinstance(message, dict) and message.get("type") == "master_steering":
                    await channel.receive_steering(message)
                receiver = asyncio.create_task(websocket.receive_json())
        result = research_task.result()
        await websocket.send_json({"type": "result", "result": result.model_dump(mode="json")})
    except (WebSocketDisconnect, asyncio.CancelledError):
        if research_task is not None:
            research_task.cancel()
            await asyncio.gather(research_task, return_exceptions=True)
    except Exception:
        if research_task is not None:
            research_task.cancel()
            await asyncio.gather(research_task, return_exceptions=True)
        try:
            await websocket.send_json(
                {
                    "type": "result",
                    "result": ResearchResult(
                        status="failed",
                        answer="Browser research could not be started or completed.",
                        limitations=["Browser or model service unavailable."],
                    ).model_dump(mode="json"),
                }
            )
        except Exception:
            pass
    finally:
        await channel.close()
        if receiver is not None and not receiver.done():
            receiver.cancel()
            await asyncio.gather(receiver, return_exceptions=True)
        if sender is not None:
            await asyncio.gather(sender, return_exceptions=True)
        context.detach(trace_token)
        _slots.release()
