"""Redis cache for successful Google Maps API JSON responses."""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

from gmaps.redis_client import get_redis
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


async def get_cached_response(key: str) -> dict[str, Any] | None:
    """Load a cached JSON response.

    Args:
        key: Redis key from ``build_cache_key``.

    Returns:
        Parsed dict if present, else None.
    """
    settings = get_settings()
    if not settings.gmaps_cache_enabled:
        return None
    raw = await get_redis().get(key)
    if raw is None:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Invalid Google Maps cache entry discarded: %s", key)
        await get_redis().delete(key)
        return None
    if isinstance(data, dict):
        return data
    return None


async def set_cached_response(key: str, data: dict[str, Any]) -> None:
    """Store a successful JSON response.

    Args:
        key: Redis key from ``build_cache_key``.
        data: Response body to cache.
    """
    settings = get_settings()
    if not settings.gmaps_cache_enabled:
        return
    ttl = settings.gmaps_cache_ttl_seconds
    await get_redis().set(key, json.dumps(data, separators=(",", ":")), ex=ttl)
