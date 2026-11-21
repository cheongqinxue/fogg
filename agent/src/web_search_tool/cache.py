"""Redis response cache for web search and extraction results."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from utils.cache.redis_cache import AsyncRedisCache
from utils.settings import get_settings
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt


class WebSearchCache(AsyncRedisCache[dict[str, Any]]):
    """Cache normalized search/extraction outputs without storing raw cache keys."""

    def __init__(self, redis_url: str, ttl: int) -> None:
        # Cache writes must fail quickly and never hold up a successful provider call.
        retry_policy = AsyncRetrying(
            retry=retry_if_exception_type((RedisConnectionError, RedisTimeoutError)),
            stop=stop_after_attempt(1),
            reraise=True,
        )
        super().__init__(
            redis_url=redis_url,
            prefix="web-search",
            ttl=ttl,
            retry_policy=retry_policy,
            on_update_failure="log",
        )

    def make_key(self, key: Any) -> str:
        identity = json.dumps(key, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(identity.encode()).hexdigest()
        return f"{self.prefix}:{digest}"

    def serialize(self, value: dict[str, Any]) -> str:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

    def deserialize(self, value: str | bytes) -> dict[str, Any]:
        result = json.loads(value)
        if not isinstance(result, dict):
            raise TypeError("Cached web-search result must be a JSON object.")
        return result


def web_search_cache_enabled() -> bool:
    return get_settings().web_search_cache_enabled


def get_web_search_cache() -> WebSearchCache:
    settings = get_settings()
    return WebSearchCache(settings.redis_url, settings.web_search_cache_ttl_seconds)
