"""Resolve the local browser service for host-side development tools."""

from __future__ import annotations

import asyncio
import ipaddress
import json


async def _docker(*args: str) -> bytes:
    proc = await asyncio.create_subprocess_exec(
        "docker", *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
    except BaseException:
        proc.kill()
        await proc.wait()
        raise
    if proc.returncode:
        raise RuntimeError("Could not inspect the local browser research container")
    return stdout


async def local_browser_service_url(port: int = 18081) -> str:
    """Find the local debug service without exposing its internal network.

    Prefer a host-published port when available. Linux Docker may omit published
    bindings for services attached only to internal networks; in that case use
    the research bridge address directly from the host.
    """
    try:
        _reader, writer = await asyncio.wait_for(asyncio.open_connection("127.0.0.1", port), 0.5)
        writer.close()
        await writer.wait_closed()
        return f"http://127.0.0.1:{port}"
    except (OSError, TimeoutError):
        pass
    containers = (
        (await _docker("ps", "-q", "--filter", "label=com.docker.compose.service=browser-research"))
        .decode()
        .splitlines()
    )
    if len(containers) != 1:
        raise RuntimeError("Start exactly one browser-research container for host debugging")
    raw = await _docker("inspect", "--format", "{{json .NetworkSettings.Networks}}", containers[0])
    networks = json.loads(raw)
    addresses = [
        value.get("IPAddress") for name, value in networks.items() if name.endswith("_research_api")
    ]
    if len(addresses) != 1:
        raise RuntimeError("Could not locate the browser research bridge address")
    address = ipaddress.ip_address(addresses[0])
    if address.version != 4:
        raise RuntimeError("Browser research bridge does not have an IPv4 address")
    return f"http://{address}:18081"
