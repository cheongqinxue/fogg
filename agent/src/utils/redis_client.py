"""Shared asynchronous Redis clients, scoped to their owning event loops."""

from __future__ import annotations

import asyncio
import weakref

from redis.asyncio import Redis

_clients: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, dict[str, Redis]] = (
    weakref.WeakKeyDictionary()
)
_overrides: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, Redis] = (
    weakref.WeakKeyDictionary()
)


def get_async_redis_client(redis_url: str) -> Redis:
    """Get the shared decoded async Redis client for this URL and event loop."""
    loop = asyncio.get_running_loop()
    override = _overrides.get(loop)
    if override is not None:
        return override
    clients = _clients.setdefault(loop, {})
    client = clients.get(redis_url)
    if client is None:
        client = Redis.from_url(redis_url, decode_responses=True)
        clients[redis_url] = client
    return client


async def close_async_redis_clients() -> None:
    """Close all shared clients owned by the current event loop."""
    loop = asyncio.get_running_loop()
    clients = _clients.pop(loop, {})
    override = _overrides.pop(loop, None)
    unique_clients = {id(client): client for client in (*clients.values(), override)}
    for client in unique_clients.values():
        if client is not None:
            await client.aclose()


def set_async_redis_client_for_tests(client: Redis | None) -> None:
    """Override the shared client in the current loop for tests."""
    loop = asyncio.get_running_loop()
    if client is None:
        _overrides.pop(loop, None)
    else:
        _overrides[loop] = client


def current_loop_client_count() -> int:
    """Return the number of URL clients cached for the current loop."""
    return len(_clients.get(asyncio.get_running_loop(), {}))
