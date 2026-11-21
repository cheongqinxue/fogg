"""Tests for shared async Redis cache behavior."""

from __future__ import annotations

import fakeredis.aioredis
import pytest
from redis.exceptions import ConnectionError as RedisConnectionError
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_fixed

from utils.cache.redis_cache import AsyncRedisCache
from utils.redis_client import (
    close_async_redis_clients,
    current_loop_client_count,
    get_async_redis_client,
    set_async_redis_client_for_tests,
)


class StringCache(AsyncRedisCache[str]):
    def make_key(self, key: str) -> str:
        return f"{self.prefix}:{key}"

    def serialize(self, value: str) -> str:
        return value

    def deserialize(self, value: str | bytes) -> str:
        return value.decode() if isinstance(value, bytes) else value


@pytest.fixture
async def redis_cache() -> StringCache:
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    set_async_redis_client_for_tests(client)
    cache = StringCache("redis://fake/0", "test-cache", ttl=60)
    yield cache
    set_async_redis_client_for_tests(None)
    await client.aclose()


@pytest.mark.asyncio
async def test_registry_reuses_client_per_url_in_event_loop() -> None:
    first = get_async_redis_client("redis://fake/0")
    second = get_async_redis_client("redis://fake/0")
    other = get_async_redis_client("redis://fake/1")
    assert first is second
    assert first is not other
    assert current_loop_client_count() == 2
    await close_async_redis_clients()
    assert current_loop_client_count() == 0


@pytest.mark.asyncio
async def test_lookup_update_and_clear(redis_cache: StringCache) -> None:
    assert await redis_cache.alookup("key") is None
    await redis_cache.aupdate("key", "value")
    assert await redis_cache.alookup("key") == "value"
    await redis_cache.aclear()
    assert await redis_cache.alookup("key") is None


@pytest.mark.asyncio
async def test_update_retries_transient_connection_errors(redis_cache: StringCache) -> None:
    calls = 0
    original_set = redis_cache.redis.set

    async def flaky_set(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls < 3:
            raise RedisConnectionError("temporary")
        return await original_set(*args, **kwargs)

    redis_cache.redis.set = flaky_set
    redis_cache.retry_policy = AsyncRetrying(
        retry=retry_if_exception_type(RedisConnectionError),
        stop=stop_after_attempt(3),
        wait=wait_fixed(0),
        reraise=True,
    )
    await redis_cache.aupdate("key", "value")
    assert calls == 3
    assert await redis_cache.alookup("key") == "value"


@pytest.mark.asyncio
async def test_update_log_policy_swallows_final_failure(redis_cache: StringCache) -> None:
    redis_cache.on_update_failure = "log"

    async def failed_set(*args, **kwargs):
        raise RedisConnectionError("offline")

    redis_cache.redis.set = failed_set
    redis_cache.retry_policy = AsyncRetrying(
        retry=retry_if_exception_type(RedisConnectionError),
        stop=stop_after_attempt(1),
        wait=wait_fixed(0),
        reraise=True,
    )
    await redis_cache.aupdate("key", "value")


@pytest.mark.asyncio
async def test_read_error_degrades_to_miss(redis_cache: StringCache) -> None:
    async def failed_get(*args, **kwargs):
        raise RedisConnectionError("offline")

    redis_cache.redis.get = failed_get
    assert await redis_cache.alookup("missing") is None


@pytest.mark.asyncio
async def test_update_without_ttl_persists_key(redis_cache: StringCache) -> None:
    cache = StringCache("redis://fake/0", "persistent-cache")
    await cache.aupdate("key", "value")
    redis_key = cache.make_key("key")
    assert await cache.redis.ttl(redis_key) == -1
    assert await cache.alookup("key") == "value"
