"""In-process gmaps benchmark harness (mocked Google HTTP)."""

from __future__ import annotations

import asyncio
import os
from typing import Any

import fakeredis.aioredis
import httpx
from tenacity import wait_fixed

from benchmarks.scenarios import Scenario
from gmaps.errors import GoogleMapsApiError
from gmaps.redis_client import set_redis_client
from gmaps.requests import PlacesTextSearchRequest
from gmaps.requests.base import close_http_client, get_http_client
from gmaps.response_cache import CACHE_KEY_PREFIX
from gmaps.settings import reset_usage_store_for_tests

SAMPLE_PLACES_RESPONSE: dict[str, Any] = {
    "places": [{"id": "places/bench", "displayName": {"text": "Bench Cafe"}}],
}

DEFAULT_REQUEST = PlacesTextSearchRequest(
    field_mask="places.id,places.displayName",
    text_query="benchmark coffee",
)


class GmapsBenchmarkHarness:
    """Configure env, Redis, and mock HTTP for one scenario."""

    def __init__(self, scenario: Scenario) -> None:
        """Store scenario; call ``setup()`` before timing."""
        self._scenario = scenario
        self._redis: fakeredis.aioredis.FakeRedis | None = None
        self._restore_retry_wait: Any | None = None

    async def setup(self) -> None:
        """Apply scenario env, inject fakeredis, and mock HTTP."""
        reset_usage_store_for_tests()
        await close_http_client()
        set_redis_client(None)

        scenario = self._scenario
        os.environ["GOOGLE_MAPS_API_KEY"] = "benchmark-key-not-for-google"
        os.environ["FOGG_ENV"] = "test"
        os.environ["GMAPS_CACHE_ENABLED"] = "true" if scenario.cache_enabled else "false"
        os.environ["GMAPS_QUOTA_TRACKING"] = "true" if scenario.quota_enabled else "false"
        os.environ["GMAPS_QUOTA_STORE"] = "redis"
        reset_usage_store_for_tests()

        self._redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
        set_redis_client(self._redis)

        latency = scenario.simulated_google_latency_sec
        if scenario.group == "failure_path":
            self._install_always_503_mock(fast_retry=True)
        else:
            self._install_success_mock(latency_sec=latency)

        if scenario.warm_cache:
            await self.invoke_once()

    async def teardown(self) -> None:
        """Release clients (optional; new setup resets state)."""
        if self._restore_retry_wait is not None:
            import gmaps.requests.base as base_module

            base_module.wait_exponential_jitter = self._restore_retry_wait
            self._restore_retry_wait = None
        await close_http_client()
        set_redis_client(None)
        reset_usage_store_for_tests()

    async def invoke_once(self) -> dict[str, Any]:
        """One end-to-end ``PlacesTextSearchRequest.call()`` (mocked HTTP)."""
        await self._prepare_iteration()
        return await DEFAULT_REQUEST.call()

    async def invoke_once_allowing_expected_failure(self) -> dict[str, Any] | None:
        """Like ``invoke_once`` but swallows ``GoogleMapsApiError`` on failure-path scenarios."""
        try:
            return await self.invoke_once()
        except GoogleMapsApiError:
            if self._scenario.group == "failure_path":
                return None
            raise

    async def _prepare_iteration(self) -> None:
        if self._scenario.clear_cache_before_each:
            await self._clear_response_cache()

    async def _clear_response_cache(self) -> None:
        if self._redis is None:
            return
        async for key in self._redis.scan_iter(match=f"{CACHE_KEY_PREFIX}*"):
            await self._redis.delete(key)

    def _install_success_mock(self, *, latency_sec: float) -> None:
        client = get_http_client()

        async def fake_post(*_args: Any, **_kwargs: Any) -> httpx.Response:
            if latency_sec > 0:
                await asyncio.sleep(latency_sec)
            request = httpx.Request("POST", "https://places.googleapis.com/v1/places:searchText")
            return httpx.Response(200, request=request, json=SAMPLE_PLACES_RESPONSE)

        client.post = fake_post  # type: ignore[method-assign]

    def _install_always_503_mock(self, *, fast_retry: bool) -> None:
        if fast_retry:
            import gmaps.requests.base as base_module

            self._restore_retry_wait = base_module.wait_exponential_jitter
            base_module.wait_exponential_jitter = lambda **_kwargs: wait_fixed(0)  # type: ignore[misc, assignment]

        client = get_http_client()

        async def fake_post(*_args: Any, **_kwargs: Any) -> httpx.Response:
            request = httpx.Request("POST", "https://places.googleapis.com/v1/places:searchText")
            return httpx.Response(503, request=request, text="simulated outage")

        client.post = fake_post  # type: ignore[method-assign]
