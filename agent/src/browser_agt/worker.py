"""Browser-only Unix socket worker and loopback-to-proxy relay."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import signal
from contextlib import suppress
from pathlib import Path
from typing import Any

from browser_agt.browser import BrowserPolicyError, BrowserRuntime

RPC_SOCKET = Path(os.environ.get("BROWSER_WORKER_SOCKET", "/run/fogg-browser/worker.sock"))
PROXY_SOCKET = Path(os.environ.get("BROWSER_PROXY_SOCKET", "/run/browser-proxy/proxy.sock"))
MAX_MESSAGE = 1_500_000
MAX_TASK_SECONDS = float(os.environ.get("BROWSER_WORKER_MAX_TASK_SECONDS", "300"))
ACTION_LIMIT = int(os.environ.get("BROWSER_WORKER_ACTION_LIMIT", "80"))
OPERATION_TIMEOUT_MS = int(os.environ.get("BROWSER_WORKER_OPERATION_TIMEOUT_MS", "10000"))
_BROWSER_SLOT = asyncio.Lock()
if not (
    1 <= MAX_TASK_SECONDS <= 300
    and 1 <= ACTION_LIMIT <= 100
    and 100 <= OPERATION_TIMEOUT_MS <= 30000
):
    raise ValueError("Browser worker limits are outside the allowed range")


def _browser_headers() -> dict[str, str]:
    """Collect explicitly configured browser identity headers."""
    mapping = {
        "BROWSER_ACCEPT_LANGUAGE": "Accept-Language",
        "BROWSER_DNT": "DNT",
        "BROWSER_SEC_CH_UA": "sec-ch-ua",
        "BROWSER_SEC_CH_UA_MOBILE": "sec-ch-ua-mobile",
        "BROWSER_SEC_CH_UA_PLATFORM": "sec-ch-ua-platform",
    }
    headers = {header: value for key, header in mapping.items() if (value := os.environ.get(key))}
    if any("\r" in value or "\n" in value for value in headers.values()):
        raise ValueError("Browser header values must not contain newlines")
    return headers


async def _write(writer: asyncio.StreamWriter, payload: dict[str, Any]) -> None:
    data = json.dumps(payload, separators=(",", ":")).encode() + b"\n"
    if len(data) > MAX_MESSAGE:
        data = b'{"ok":false,"error":"worker response too large"}\n'
    writer.write(data)
    await writer.drain()


async def _handle_rpc(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    """One client connection owns one context; disconnect guarantees cleanup."""
    runtime: BrowserRuntime | None = None
    job = None
    try:
        async with asyncio.timeout(MAX_TASK_SECONDS):
            while True:
                line = await reader.readline()
                if not line:
                    break
                if len(line) > MAX_MESSAGE or not line.endswith(b"\n"):
                    await _write(writer, {"ok": False, "error": "message too large"})
                    break
                try:
                    request = json.loads(line)
                    if not isinstance(request, dict) or not isinstance(request.get("op"), str):
                        raise ValueError("invalid request")
                    op = request["op"]
                    if op == "start" and runtime is None:
                        # Network namespace has no interfaces; destination safety belongs to
                        # the mandatory proxy, which resolves and pins public addresses.
                        runtime = BrowserRuntime(
                            proxy_server="http://127.0.0.1:18882",
                            allow_local=True,
                            action_limit=ACTION_LIMIT,
                            timeout_ms=OPERATION_TIMEOUT_MS,
                            recording_dir=os.environ.get("BROWSER_RECORDING_DIR", "/recordings"),
                            profile_dir=os.environ.get("BROWSER_PROFILE_DIR", "/browser-profile"),
                            headless=False,
                            browser_channel="chrome",
                            user_agent=os.environ.get("BROWSER_USER_AGENT") or None,
                            extra_http_headers=_browser_headers(),
                        )
                        await runtime.__aenter__()
                        job = await runtime.create_job()
                        result: Any = {"started": True}
                    elif runtime is None or job is None:
                        raise ValueError("start is required before browser operations")
                    elif op == "navigate":
                        await job.navigate(request["url"])
                        result = None
                    elif op == "observe":
                        observation = await job.observe()
                        result = {
                            "url": observation.url,
                            "title": observation.title,
                            "text": observation.text,
                            "scroll_target": observation.scroll_target,
                            "scroll_top": observation.scroll_top,
                            "scroll_height": observation.scroll_height,
                            "client_height": observation.client_height,
                            "at_scroll_end": observation.at_scroll_end,
                            "scroll_position_changed": observation.scroll_position_changed,
                            "screenshot_changed": observation.screenshot_changed,
                            "elements": [
                                {
                                    "element_id": e.element_id,
                                    "kind": e.kind,
                                    "label": e.label,
                                    "input_type": e.input_type,
                                }
                                for e in observation.elements
                            ],
                            "screenshot": (
                                base64.b64encode(observation.screenshot).decode("ascii")
                                if observation.screenshot is not None
                                else None
                            ),
                        }
                    elif op == "click":
                        await job.click(request["element_id"])
                        result = None
                    elif op == "fill":
                        await job.fill(request["element_id"], request["value"])
                        result = None
                    elif op == "click_at":
                        await job.click_at(request["x"], request["y"])
                        result = None
                    elif op == "type_text":
                        await job.type_text(request["value"])
                        result = None
                    elif op == "hotkey":
                        await job.press_hotkey(request["key"])
                        result = None
                    elif op == "scroll_at":
                        await job.scroll_at(request["x"], request["y"], request["direction"])
                        result = None
                    elif op == "wait":
                        await job.wait(request.get("seconds", 2))
                        result = None
                    elif op == "back":
                        await job.back()
                        result = None
                    elif op == "close":
                        await job.close()
                        job = None
                        await _write(writer, {"ok": True, "result": None})
                        break
                    else:
                        raise ValueError("unknown browser operation")
                    await _write(writer, {"ok": True, "result": result})
                except BrowserPolicyError as exc:
                    await _write(writer, {"ok": False, "policy": True, "error": str(exc)})
                except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                    await _write(writer, {"ok": False, "error": "invalid browser worker request"})
    except (TimeoutError, asyncio.IncompleteReadError):
        pass
    except Exception:
        with suppress(Exception):
            await _write(writer, {"ok": False, "error": "browser worker operation failed"})
    finally:
        if runtime is not None:
            await runtime.close()
        writer.close()
        with suppress(OSError):
            await writer.wait_closed()


async def _handle_rpc_serialized(
    reader: asyncio.StreamReader, writer: asyncio.StreamWriter
) -> None:
    """Serialize access to the persistent Chrome profile."""
    async with _BROWSER_SLOT:
        await _handle_rpc(reader, writer)


async def _relay_connection(
    client_reader: asyncio.StreamReader, client_writer: asyncio.StreamWriter
) -> None:
    try:
        upstream_reader, upstream_writer = await asyncio.open_unix_connection(PROXY_SOCKET)
    except OSError:
        client_writer.close()
        await client_writer.wait_closed()
        return

    async def pump(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            while data := await reader.read(65_536):
                writer.write(data)
                await writer.drain()
        finally:
            with suppress(Exception):
                writer.write_eof()

    try:
        await asyncio.gather(
            pump(client_reader, upstream_writer), pump(upstream_reader, client_writer)
        )
    finally:
        upstream_writer.close()
        client_writer.close()
        with suppress(Exception):
            await upstream_writer.wait_closed()
        with suppress(Exception):
            await client_writer.wait_closed()


async def serve() -> None:
    RPC_SOCKET.parent.mkdir(parents=True, exist_ok=True)
    with suppress(FileNotFoundError):
        RPC_SOCKET.unlink()
    server = await asyncio.start_unix_server(
        _handle_rpc_serialized, path=RPC_SOCKET, limit=MAX_MESSAGE
    )
    os.chmod(RPC_SOCKET, 0o660)
    proxy = await asyncio.start_server(_relay_connection, "127.0.0.1", 18882)
    for sig in (signal.SIGTERM, signal.SIGINT):
        asyncio.get_running_loop().add_signal_handler(sig, server.close)
        asyncio.get_running_loop().add_signal_handler(sig, proxy.close)
    async with server, proxy:
        await asyncio.gather(server.serve_forever(), proxy.serve_forever())


if __name__ == "__main__":
    asyncio.run(serve())
