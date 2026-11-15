"""Extensible async Redis cache base with shared connection and failure policy."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from typing import Literal
from typing import Any, Generic, TypeVar

from redis.asyncio import Redis
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from agent_utils.redis_client import get_async_redis_client

T = TypeVar("T")
logger = logging.getLogger(__name__)


def default_redis_retry_policy() -> AsyncRetrying:
    """Three retries with jitter for transient Redis connection failures."""
    return AsyncRetrying(
        retry=retry_if_exception_type((RedisConnectionError, RedisTimeoutError)),
        stop=stop_after_attempt(4),
        wait=wait_exponential_jitter(multiplier=0.1, max=1.0),
        reraise=True,
    )


class AsyncRedisCache(ABC, Generic[T]):
    """Base class for async caches that share Redis behavior across API modules."""

    def __init__(
        self,
        redis_url: str,
        prefix: str,
        ttl: int | None = None,
        retry_policy: AsyncRetrying | None = None,
        on_update_failure: Literal["log", "raise"] = "raise",
    ) -> None:
        if ttl is not None and ttl < 1:
            raise ValueError("ttl must be at least 1 second when specified")
        if not prefix:
            raise ValueError("prefix must not be empty")
        if on_update_failure not in {"log", "raise"}:
            raise ValueError("on_update_failure must be 'log' or 'raise'")
        self.redis_url = redis_url
        self.ttl = ttl
        self.prefix = prefix
        self.retry_policy = retry_policy or default_redis_retry_policy()
        self.on_update_failure = on_update_failure

    @property
    def redis(self) -> Redis:
        """Shared async client for this URL and event loop."""
        return get_async_redis_client(self.redis_url)

    @abstractmethod
    def make_key(self, key: Any) -> str:
        """Return the full Redis key, including the cache prefix."""

    @abstractmethod
    def serialize(self, value: T) -> str | bytes:
        """Serialize a cache value for Redis storage."""

    @abstractmethod
    def deserialize(self, value: str | bytes) -> T:
        """Deserialize a Redis value."""

    async def alookup(self, key: Any) -> T | None:
        """Look up a value; Redis read failures degrade to a cache miss."""
        try:
            raw = await self.redis.get(self.make_key(key))
        except Exception:
            logger.exception("Redis cache lookup failed; treating as miss")
            return None
        if raw is None:
            return None
        try:
            return self.deserialize(raw)
        except Exception:
            logger.exception("Invalid cache value; treating as miss")
            return None

    async def aupdate(self, key: Any, value: T) -> None:
        """Store a value with optional TTL and configured retry/failure behavior."""

        async def write() -> None:
            redis_key = self.make_key(key)
            serialized = self.serialize(value)
            if self.ttl is None:
                await self.redis.set(redis_key, serialized)
            else:
                await self.redis.set(redis_key, serialized, ex=self.ttl)

        try:
            await self._retry(write)
        except Exception:
            if self.on_update_failure == "log":
                logger.exception("Redis cache update failed")
                return
            raise

    async def aclear(self) -> None:
        """Delete keys in this cache namespace; failures are logged and raised."""

        async def clear() -> None:
            cursor: int = 0
            pattern = f"{self.prefix}:*"
            while True:
                cursor, keys = await self.redis.scan(cursor=cursor, match=pattern, count=500)
                if keys:
                    await self.redis.delete(*keys)
                if cursor == 0:
                    return

        try:
            await self._retry(clear)
        except Exception:
            logger.exception("Redis cache clear failed")
            raise

    async def _retry(self, operation: Callable[[], Awaitable[None]]) -> None:
        async for attempt in self.retry_policy:
            with attempt:
                await operation()
