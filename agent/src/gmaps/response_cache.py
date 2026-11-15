"""Redis cache for successful Google Maps API JSON responses."""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

from agent_utils.cache.redis_cache import AsyncRedisCache
from gmaps.settings import get_settings

logger = logging.getLogger(__name__)

CACHE_KEY_PREFIX = "gmaps:cache:"


def build_cache_key(
    method: str,
    url: str,
    field_mask: str | None,
    payload: dict[str, Any] | None,
) -> str:
    """Stable Redis key for a Google Maps request identity (excludes API key).

    Args:
        method: HTTP method.
        url: Full request URL without query string for GET (params in payload).
        field_mask: X-Goog-FieldMask when applicable.
        payload: JSON body for POST, or query params for GET (without ``key``).

    Returns:
        Redis key string.
    """
    canonical = json.dumps(
        {
            "method": method.upper(),
            "url": url,
            "field_mask": field_mask or "",
            "payload": payload or {},
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"{CACHE_KEY_PREFIX}{digest}"


class _GoogleMapsResponseCache(AsyncRedisCache[dict[str, Any]]):
    """JSON cache specialization for Google Maps responses."""

    def make_key(self, key: Any) -> str:
        return str(key)

    def serialize(self, value: dict[str, Any]) -> str:
        return json.dumps(value, separators=(",", ":"))

    def deserialize(self, value: str | bytes) -> dict[str, Any]:
        decoded = json.loads(value)
        if not isinstance(decoded, dict):
            raise ValueError("cached Maps response must be a JSON object")
        return decoded


_cache: _GoogleMapsResponseCache | None = None


def _get_cache() -> _GoogleMapsResponseCache:
    global _cache
    settings = get_settings()
    if (
        _cache is None
        or _cache.ttl != settings.gmaps_cache_ttl_seconds
        or _cache.redis_url != settings.redis_url
    ):
        _cache = _GoogleMapsResponseCache(
            redis_url=settings.redis_url,
            ttl=settings.gmaps_cache_ttl_seconds,
            prefix=CACHE_KEY_PREFIX.rstrip(":"),
            on_update_failure="log",
        )
    return _cache


async def get_cached_response(key: str) -> dict[str, Any] | None:
    """Load a cached JSON response, returning a miss when disabled or unavailable."""
    if not get_settings().gmaps_cache_enabled:
        return None
    return await _get_cache().alookup(key)


async def set_cached_response(key: str, data: dict[str, Any]) -> None:
    """Store a successful Google Maps response as best-effort cache data."""
    if not get_settings().gmaps_cache_enabled:
        return
    await _get_cache().aupdate(key, data)
