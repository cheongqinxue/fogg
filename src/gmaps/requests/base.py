"""Base class for Google Maps API requests (cache, quota, retry, HTTP)."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Generic, TypeVar

import httpx
from pydantic import BaseModel, ConfigDict
from tenacity import AsyncRetrying, retry_if_exception, stop_after_attempt, wait_exponential_jitter

from gmaps.errors import GmapsQuotaExceededError, GoogleMapsApiError
from gmaps.quota.caps import SKU_FREE_CAP
from gmaps.quota.store import UsageStore, current_period
from gmaps.quota.types import BillableEvent
from gmaps.requests.quota_balance import QuotaBalance
from gmaps.requests.sku import BillableSKU
from gmaps.response_cache import get_cached_response, set_cached_response
from gmaps.settings import GmapsSettings, get_settings, get_usage_store

logger = logging.getLogger(__name__)

TResponse = TypeVar("TResponse")

RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})


def requests_base_max_retries() -> int:
    """Configured retry count after the first HTTP attempt (``GMAPS_REQUESTS_BASE_MAX_RETRIES``)."""
    return get_settings().gmaps_requests_base_max_retries


def requests_base_max_attempts() -> int:
    """Total HTTP tries per ``call()`` including the first attempt."""
    return requests_base_max_retries() + 1

_http_client: httpx.AsyncClient | None = None


def get_http_client() -> httpx.AsyncClient:
    """Shared async HTTP client for Google Maps requests."""
    global _http_client
    if _http_client is None:
        _http_client = httpx.AsyncClient(timeout=httpx.Timeout(120.0))
    return _http_client


async def close_http_client() -> None:
    """Close the shared HTTP client (application shutdown)."""
    global _http_client
    if _http_client is not None:
        await _http_client.aclose()
        _http_client = None


class GoogleMapRequest(BaseModel, ABC, Generic[TResponse]):
    """One Google Maps operation: quota, cache, retry, and HTTP in ``call()``."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    @property
    @abstractmethod
    def billable_sku(self) -> BillableSKU:
        """Primary SKU for ``check_quota()``."""

    @abstractmethod
    def _billable_for_attempt(self) -> list[tuple[BillableSKU, int]]:
        """SKU and units charged per HTTP attempt (written explicitly on each subclass)."""

    @abstractmethod
    def _cache_key(self) -> str:
        """Redis cache key for this request instance."""

    @abstractmethod
    async def _do_http(self) -> httpx.Response:
        """Perform a single HTTP attempt (no retry loop)."""

    def _to_response(self, data: dict[str, Any]) -> TResponse:
        """Map Google JSON to the generic response type."""
        return data  # type: ignore[return-value]

    def _to_billable_events(self) -> list[BillableEvent]:
        return [
            BillableEvent(sku=sku.value, units=units)
            for sku, units in self._billable_for_attempt()
        ]

    async def check_quota(self) -> QuotaBalance:
        """Return local ``used`` and remaining ``balance`` for ``billable_sku``."""
        sku = self.billable_sku.value
        store = get_usage_store()
        totals = await store.totals()
        used = int(totals.get(sku, 0))
        cap = SKU_FREE_CAP.get(sku)
        balance = max(cap - used, 0) if cap is not None else 0
        return QuotaBalance(used=used, balance=balance)

    async def call(self) -> TResponse:
        """Run cache lookup, retryable HTTP with per-attempt billing, then cache store."""
        cache_key = self._cache_key()
        cached = await get_cached_response(cache_key)
        if cached is not None:
            logger.debug("Google Maps cache hit: %s", cache_key)
            return self._to_response(cached)

        data = await self._call_with_retry()
        await set_cached_response(cache_key, data)
        return self._to_response(data)

    async def _call_with_retry(self) -> dict[str, Any]:
        settings = get_settings()
        try:
            async for attempt in AsyncRetrying(
                retry=retry_if_exception(self._is_retryable_error),
                stop=stop_after_attempt(requests_base_max_attempts()),
                wait=wait_exponential_jitter(
                    initial=settings.gmaps_requests_base_retry_wait_initial_seconds,
                    max=settings.gmaps_requests_base_retry_wait_max_seconds,
                ),
                before_sleep=self._before_sleep_log,
                reraise=True,
            ):
                with attempt:
                    async with self._billing_scope():
                        response = await self._do_http()
                    return self._parse_json_response(response)
        except GmapsQuotaExceededError:
            raise
        except httpx.HTTPStatusError as exc:
            self._raise_google_api_error(exc)
        except Exception as exc:
            self._raise_google_api_error(exc)
        raise RuntimeError("unreachable")

    def _parse_json_response(self, response: httpx.Response) -> dict[str, Any]:
        response.raise_for_status()
        data: dict[str, Any] = response.json()
        return data

    def _is_retryable_error(self, exc: BaseException) -> bool:
        if isinstance(exc, httpx.HTTPStatusError):
            return exc.response.status_code in RETRYABLE_STATUS_CODES
        return isinstance(
            exc,
            (
                httpx.ConnectError,
                httpx.ReadTimeout,
                httpx.WriteTimeout,
                httpx.PoolTimeout,
                httpx.NetworkError,
            ),
        )

    @staticmethod
    def _request_was_executed(exc: BaseException | None) -> bool:
        if exc is None:
            return True
        if isinstance(exc, httpx.HTTPStatusError):
            return True
        return not isinstance(
            exc,
            (
                httpx.ConnectError,
                httpx.ReadTimeout,
                httpx.WriteTimeout,
                httpx.PoolTimeout,
                httpx.NetworkError,
            ),
        )

    @asynccontextmanager
    async def _billing_scope(self) -> AsyncIterator[None]:
        settings = get_settings()
        events = self._to_billable_events()
        if not events:
            yield
            return
        if not settings.effective_quota_tracking and not settings.effective_quota_enforce:
            yield
            return

        store = get_usage_store()
        billed = False
        try:
            if settings.effective_quota_enforce:
                new_totals = await store.try_reserve(events)
                billed = True
                await self._log_quota_warnings(store, events, settings, new_totals)
            elif settings.effective_quota_tracking:
                await store.record(events)
                billed = True
            if settings.gmaps_quota_log and billed:
                logger.info("gmaps quota attempt -> %s", events)
            yield
        except BaseException as exc:
            if billed and not isinstance(exc, GmapsQuotaExceededError):
                if not self._request_was_executed(exc):
                    await store.refund(events)
            raise

    async def _log_quota_warnings(
        self,
        store: UsageStore,
        events: list[BillableEvent],
        settings: GmapsSettings,
        new_totals: dict[str, int],
    ) -> None:
        ratio_threshold = settings.gmaps_quota_warn_ratio
        remaining_floor = settings.gmaps_quota_warn_remaining
        period = current_period()
        for event in events:
            cap = SKU_FREE_CAP.get(event.sku)
            if cap is None or cap <= 0:
                continue
            used = new_totals.get(event.sku, 0)
            remaining = max(cap - used, 0)
            used_ratio = used / cap
            should_warn = used_ratio >= ratio_threshold or remaining <= remaining_floor
            if not should_warn:
                continue
            if await store.quota_warning_already_logged(event.sku, period=period):
                continue
            await store.mark_quota_warning_logged(event.sku, period=period)
            logger.warning(
                "Google Maps quota threshold for %s: used %s of %s (%s remaining) — local estimate",
                event.sku,
                used,
                cap,
                remaining,
            )

    def _before_sleep_log(self, retry_state: Any) -> None:
        outcome = retry_state.outcome
        if outcome is None:
            return
        exc = outcome.exception()
        if exc is None:
            return
        attempt = retry_state.attempt_number
        max_retries = requests_base_max_retries()
        logger.warning(
            "Google Maps API retry %s/%s: %s",
            attempt,
            max_retries,
            self._format_google_error(exc),
        )

    def _raise_google_api_error(self, exc: BaseException) -> dict[str, Any]:
        message = self._format_google_error(exc)
        if self._is_retryable_error(exc):
            logger.error(
                "Google Maps API failed after %s retries: %s",
                requests_base_max_retries(),
                message,
                exc_info=False,
            )
        else:
            logger.error("Google Maps API error (not retrying): %s", message, exc_info=False)
        raise GoogleMapsApiError(message) from exc

    @staticmethod
    def _format_google_error(exc: BaseException) -> str:
        if isinstance(exc, httpx.HTTPStatusError):
            response = exc.response
            snippet = (response.text or "")[:500].strip()
            if snippet:
                return f"HTTP {response.status_code} from Google Maps: {snippet}"
            return f"HTTP {response.status_code} from Google Maps"
        return f"Google Maps request failed: {type(exc).__name__}: {exc}"

    def _api_key_header(self) -> dict[str, str]:
        settings = get_settings()
        if not settings.google_maps_api_key:
            msg = "GOOGLE_MAPS_API_KEY is not set"
            raise RuntimeError(msg)
        return {"X-Goog-Api-Key": settings.google_maps_api_key}
