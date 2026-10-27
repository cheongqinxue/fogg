"""Shared async Redis connection (quota now; response cache later)."""

from __future__ import annotations

from redis.asyncio import Redis

_redis: Redis | None = None


def get_redis(*, url: str | None = None) -> Redis:
    """Return a process-wide Redis client (lazy singleton).

    Args:
        url: Override URL; defaults to ``GMAPS_REDIS_URL``.

    Returns:
        Connected ``redis.asyncio.Redis`` instance with ``decode_responses=True``.
    """
    global _redis
    if _redis is None:
        from gmaps.settings import get_settings

        settings = get_settings()
        _redis = Redis.from_url(url or settings.gmaps_redis_url, decode_responses=True)
    return _redis


async def close_redis() -> None:
    """Close the shared Redis connection (app shutdown / tests)."""
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None


def set_redis_client(client: Redis | None) -> None:
    """Inject a Redis client (tests or custom wiring)."""
    global _redis
    _redis = client
