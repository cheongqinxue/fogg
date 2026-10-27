"""Tests for GoogleMapRequest subclasses (cache, quota, retry)."""

import json
import logging

import httpx
import pytest
import fakeredis.aioredis
from pydantic import ValidationError
from pytest import LogCaptureFixture
from tenacity import wait_fixed

from gmaps.errors import GmapsQuotaExceededError, GoogleMapsApiError
from gmaps.quota.caps import SKU_FREE_CAP
from gmaps.quota.store import RedisUsageStore
from gmaps.quota.types import BillableEvent
from gmaps.redis_client import set_redis_client
from gmaps.requests import (
    DirectionsRequest,
    GeocodeRequest,
    PlacesAutocompleteRequest,
    PlacesGetRequest,
    PlacesSearchNearbyRequest,
    PlacesTextSearchRequest,
    QuotaBalance,
    RoutesComputeRouteMatrixRequest,
    RoutesComputeRoutesRequest,
)
from gmaps.requests.places import Circle, LocationRestriction
from gmaps.requests.routes import Location, RouteMatrixWaypoint, Waypoint
from gmaps.requests.sku import BillableSKU
from gmaps.requests._google_json import LatLng
from gmaps.requests.base import (
    close_http_client,
    get_http_client,
    requests_base_max_attempts,
    requests_base_max_retries,
)
from gmaps.response_cache import build_cache_key
from gmaps.settings import reset_usage_store_for_tests

BASE_LOGGER = "gmaps.requests.base"


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    reset_usage_store_for_tests()
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "test-key")
    monkeypatch.setenv("GMAPS_CACHE_ENABLED", "false")
    monkeypatch.setenv("GMAPS_QUOTA_TRACKING", "false")
    monkeypatch.setenv("GMAPS_QUOTA_ENFORCE", "false")


@pytest.fixture
def fast_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "gmaps.requests.base.wait_exponential_jitter",
        lambda **_kwargs: wait_fixed(0),
    )


@pytest.mark.asyncio
async def test_places_text_search_returns_json(
    env: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Successful call returns Google JSON unchanged."""
    async def fake_post(*_args, **_kwargs):
        request = httpx.Request("POST", "https://example.com")
        return httpx.Response(200, request=request, json={"places": []})

    monkeypatch.setattr(get_http_client(), "post", fake_post)
    req = PlacesTextSearchRequest(field_mask="places.id", text_query="coffee")
    result = await req.call()
    assert result == {"places": []}


def test_validation_rejects_empty_query() -> None:
    with pytest.raises(ValidationError):
        PlacesTextSearchRequest(field_mask="places.id", text_query="")


@pytest.mark.asyncio
async def test_check_quota_returns_two_numbers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reset_usage_store_for_tests()
    monkeypatch.setenv("GMAPS_QUOTA_STORE", "redis")
    fake = fakeredis.aioredis.FakeRedis(decode_responses=True)
    set_redis_client(fake)
    store = RedisUsageStore(fake)
    cap = SKU_FREE_CAP["places_text_search_pro"]
    assert cap is not None
    await store.try_reserve([BillableEvent("places_text_search_pro", 100)])

    req = PlacesTextSearchRequest(field_mask="places.id", text_query="x")
    balance = await req.check_quota()
    assert balance == QuotaBalance(used=100, balance=cap - 100)
    reset_usage_store_for_tests()
    set_redis_client(None)


@pytest.mark.asyncio
async def test_cache_hit_skips_http_and_quota(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reset_usage_store_for_tests()
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "test-key")
    monkeypatch.setenv("GMAPS_CACHE_ENABLED", "true")
    monkeypatch.setenv("GMAPS_QUOTA_TRACKING", "true")
    fake = fakeredis.aioredis.FakeRedis(decode_responses=True)
    set_redis_client(fake)
    calls = {"n": 0}

    async def fake_post(*_args, **_kwargs):
        calls["n"] += 1
        request = httpx.Request("POST", "https://example.com")
        return httpx.Response(200, request=request, json={"places": [{"id": "a"}]})

    monkeypatch.setattr(get_http_client(), "post", fake_post)
    req = PlacesTextSearchRequest(field_mask="places.id", text_query="coffee")
    first = await req.call()
    second = await req.call()
    assert first == second
    assert calls["n"] == 1
    store = RedisUsageStore(fake)
    totals = await store.totals()
    assert totals.get("places_text_search_pro") == 1
    reset_usage_store_for_tests()
    set_redis_client(None)


@pytest.mark.asyncio
async def test_retries_count_each_attempt(
    monkeypatch: pytest.MonkeyPatch,
    fast_retry: None,
) -> None:
    reset_usage_store_for_tests()
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "test-key")
    monkeypatch.setenv("GMAPS_CACHE_ENABLED", "false")
    monkeypatch.setenv("GMAPS_QUOTA_TRACKING", "true")
    fake = fakeredis.aioredis.FakeRedis(decode_responses=True)
    set_redis_client(fake)
    calls = {"n": 0}

    async def fake_post(*_args, **_kwargs):
        calls["n"] += 1
        request = httpx.Request("POST", "https://example.com")
        if calls["n"] < 3:
            return httpx.Response(503, request=request, text="busy")
        return httpx.Response(200, request=request, json={"places": []})

    monkeypatch.setattr(get_http_client(), "post", fake_post)
    req = PlacesTextSearchRequest(field_mask="places.id", text_query="coffee")
    await req.call()
    assert calls["n"] == 3
    store = RedisUsageStore(fake)
    assert store and (await store.totals()).get("places_text_search_pro") == 3
    reset_usage_store_for_tests()
    set_redis_client(None)


@pytest.mark.asyncio
async def test_enforcement_blocks_at_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reset_usage_store_for_tests()
    monkeypatch.setenv("FOGG_ENV", "dev")
    monkeypatch.setenv("GMAPS_QUOTA_ENFORCE", "true")
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "test-key")
    monkeypatch.setenv("GMAPS_CACHE_ENABLED", "false")
    fake = fakeredis.aioredis.FakeRedis(decode_responses=True)
    set_redis_client(fake)
    store = RedisUsageStore(fake)
    cap = SKU_FREE_CAP["places_text_search_pro"]
    assert cap is not None
    await store.try_reserve([BillableEvent("places_text_search_pro", cap)])
    calls = {"n": 0}

    async def fake_post(*_args, **_kwargs):
        calls["n"] += 1
        return httpx.Response(200, request=httpx.Request("POST", "https://x"), json={})

    monkeypatch.setattr(get_http_client(), "post", fake_post)
    req = PlacesTextSearchRequest(field_mask="places.id", text_query="coffee")
    with pytest.raises(GmapsQuotaExceededError):
        await req.call()
    assert calls["n"] == 0
    reset_usage_store_for_tests()
    set_redis_client(None)


@pytest.mark.asyncio
async def test_network_failure_refunds_quota(
    monkeypatch: pytest.MonkeyPatch,
    fast_retry: None,
) -> None:
    reset_usage_store_for_tests()
    monkeypatch.setenv("GMAPS_QUOTA_ENFORCE", "true")
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "test-key")
    monkeypatch.setenv("GMAPS_CACHE_ENABLED", "false")
    fake = fakeredis.aioredis.FakeRedis(decode_responses=True)
    set_redis_client(fake)

    async def fake_post(*_args, **_kwargs):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(get_http_client(), "post", fake_post)
    req = PlacesTextSearchRequest(field_mask="places.id", text_query="coffee")
    with pytest.raises(GoogleMapsApiError):
        await req.call()
    store = RedisUsageStore(fake)
    assert (await store.totals()).get("places_text_search_pro", 0) == 0
    reset_usage_store_for_tests()
    set_redis_client(None)


@pytest.mark.asyncio
async def test_http_error_after_response_keeps_quota(
    monkeypatch: pytest.MonkeyPatch,
    fast_retry: None,
) -> None:
    reset_usage_store_for_tests()
    monkeypatch.setenv("GMAPS_QUOTA_ENFORCE", "true")
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "test-key")
    monkeypatch.setenv("GMAPS_CACHE_ENABLED", "false")
    fake = fakeredis.aioredis.FakeRedis(decode_responses=True)
    set_redis_client(fake)

    async def fake_post(*_args, **_kwargs):
        request = httpx.Request("POST", "https://example.com")
        return httpx.Response(400, request=request, text="bad")

    monkeypatch.setattr(get_http_client(), "post", fake_post)
    req = PlacesTextSearchRequest(field_mask="places.id", text_query="coffee")
    with pytest.raises(GoogleMapsApiError):
        await req.call()
    store = RedisUsageStore(fake)
    assert (await store.totals()).get("places_text_search_pro") == 1
    reset_usage_store_for_tests()
    set_redis_client(None)


@pytest.mark.asyncio
async def test_exhausted_retries_log_error(
    monkeypatch: pytest.MonkeyPatch,
    caplog: LogCaptureFixture,
    fast_retry: None,
) -> None:
    monkeypatch.setenv("FOGG_ENV", "test")
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "test-key")
    monkeypatch.setenv("GMAPS_CACHE_ENABLED", "false")
    monkeypatch.setenv("GMAPS_QUOTA_TRACKING", "false")
    monkeypatch.setenv("GMAPS_QUOTA_ENFORCE", "false")
    reset_usage_store_for_tests()
    await close_http_client()
    calls = {"n": 0}

    async def fake_post(*_args, **_kwargs):
        calls["n"] += 1
        request = httpx.Request("POST", "https://example.com")
        return httpx.Response(503, request=request, text="out")

    monkeypatch.setattr(get_http_client(), "post", fake_post)
    req = PlacesTextSearchRequest(field_mask="places.id", text_query="coffee")
    with caplog.at_level(logging.WARNING, logger=BASE_LOGGER):
        with pytest.raises(GoogleMapsApiError, match="503"):
            await req.call()
    assert calls["n"] == requests_base_max_attempts()
    retry_msgs = [r.getMessage() for r in caplog.records if "retry" in r.getMessage().lower()]
    assert len(retry_msgs) == requests_base_max_retries()


@pytest.mark.asyncio
async def test_max_retries_from_env(
    monkeypatch: pytest.MonkeyPatch,
    fast_retry: None,
) -> None:
    monkeypatch.setenv("FOGG_ENV", "test")
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "test-key")
    monkeypatch.setenv("GMAPS_CACHE_ENABLED", "false")
    monkeypatch.setenv("GMAPS_QUOTA_TRACKING", "false")
    monkeypatch.setenv("GMAPS_REQUESTS_BASE_MAX_RETRIES", "2")
    reset_usage_store_for_tests()
    await close_http_client()
    calls = {"n": 0}

    async def fake_post(*_args, **_kwargs):
        calls["n"] += 1
        request = httpx.Request("POST", "https://example.com")
        return httpx.Response(503, request=request, text="busy")

    monkeypatch.setattr(get_http_client(), "post", fake_post)
    req = PlacesTextSearchRequest(field_mask="places.id", text_query="coffee")
    with pytest.raises(GoogleMapsApiError):
        await req.call()
    assert calls["n"] == 3


def _tokyo_osaka_routes() -> tuple[Waypoint, Waypoint]:
    origin = Waypoint(address="Tokyo Station, Japan")
    destination = Waypoint(address="Osaka Station, Japan")
    return origin, destination


def _sample_requests() -> list[tuple[str, object, dict[str, object]]]:
    """HTTP method, request instance, mock JSON body."""
    latlng = LatLng(latitude=35.681, longitude=139.767)
    circle = Circle(center=latlng, radius=1000.0)
    origin, destination = _tokyo_osaka_routes()
    matrix_origin = RouteMatrixWaypoint(waypoint=origin)
    matrix_dest = RouteMatrixWaypoint(waypoint=destination)
    return [
        (
            "post",
            PlacesTextSearchRequest(field_mask="places.id", text_query="coffee"),
            {"places": []},
        ),
        (
            "post",
            PlacesSearchNearbyRequest(
                field_mask="places.id",
                location_restriction=LocationRestriction(circle=circle),
                included_types=["cafe"],
            ),
            {"places": []},
        ),
        (
            "post",
            PlacesAutocompleteRequest(field_mask="suggestions.placePrediction", input="coff"),
            {"suggestions": []},
        ),
        (
            "get",
            PlacesGetRequest(field_mask="places.id", place_id="ChIJN1t_tDeuEmsRUsoyG83frY4"),
            {"id": "ChIJN1t_tDeuEmsRUsoyG83frY4"},
        ),
        (
            "post",
            RoutesComputeRoutesRequest(
                field_mask="routes.duration",
                origin=origin,
                destination=destination,
            ),
            {"routes": []},
        ),
        (
            "post",
            RoutesComputeRouteMatrixRequest(
                field_mask="routes.duration",
                origins=[matrix_origin],
                destinations=[matrix_dest],
            ),
            {"routes": []},
        ),
        (
            "get",
            GeocodeRequest(address="1600 Amphitheatre Parkway"),
            {"results": []},
        ),
        (
            "get",
            DirectionsRequest(origin="Tokyo", destination="Osaka"),
            {"routes": []},
        ),
    ]


@pytest.mark.parametrize(
    ("http_method", "request_instance", "response_json"),
    _sample_requests(),
    ids=[
        "places_text_search",
        "places_search_nearby",
        "places_autocomplete",
        "places_get",
        "routes_compute_routes",
        "routes_compute_route_matrix",
        "geocode",
        "directions",
    ],
)
@pytest.mark.asyncio
async def test_each_request_class_call(
    env: None,
    monkeypatch: pytest.MonkeyPatch,
    http_method: str,
    request_instance: object,
    response_json: dict[str, object],
) -> None:
    """Every public request class completes call() against mocked HTTP."""
    calls = {"n": 0}

    async def fake_post(*_args, **_kwargs):
        calls["n"] += 1
        request = httpx.Request("POST", "https://example.com")
        return httpx.Response(200, request=request, json=response_json)

    async def fake_get(*_args, **_kwargs):
        calls["n"] += 1
        request = httpx.Request("GET", "https://example.com")
        return httpx.Response(200, request=request, json=response_json)

    client = get_http_client()
    if http_method == "post":
        monkeypatch.setattr(client, "post", fake_post)
    else:
        monkeypatch.setattr(client, "get", fake_get)

    result = await request_instance.call()  # type: ignore[attr-defined]
    assert result == response_json
    assert calls["n"] == 1


@pytest.mark.parametrize(
    ("request_instance", "expected_sku"),
    [
        (
            PlacesTextSearchRequest(field_mask="places.id", text_query="x"),
            BillableSKU.PLACES_TEXT_SEARCH_PRO,
        ),
        (
            PlacesAutocompleteRequest(field_mask="suggestions.placePrediction", input="a"),
            BillableSKU.PLACES_AUTOCOMPLETE,
        ),
        (
            GeocodeRequest(address="Paris"),
            BillableSKU.GEOCODING,
        ),
        (
            RoutesComputeRouteMatrixRequest(
                field_mask="routes.duration",
                origins=[RouteMatrixWaypoint(waypoint=Waypoint(address="A"))],
                destinations=[RouteMatrixWaypoint(waypoint=Waypoint(address="B"))],
            ),
            BillableSKU.ROUTES_MATRIX_ESSENTIALS,
        ),
    ],
)
def test_billable_sku_on_subclass(request_instance: object, expected_sku: BillableSKU) -> None:
    assert request_instance.billable_sku == expected_sku  # type: ignore[attr-defined]


def test_route_matrix_bills_element_count() -> None:
    origin, destination = _tokyo_osaka_routes()
    req = RoutesComputeRouteMatrixRequest(
        field_mask="routes.duration",
        origins=[
            RouteMatrixWaypoint(waypoint=origin),
            RouteMatrixWaypoint(waypoint=Waypoint(address="Yokohama")),
        ],
        destinations=[RouteMatrixWaypoint(waypoint=destination)],
    )
    assert req._billable_for_attempt() == [(BillableSKU.ROUTES_MATRIX_ESSENTIALS, 2)]


@pytest.mark.asyncio
async def test_cache_key_stable(env: None) -> None:
    req = PlacesTextSearchRequest(field_mask="places.id", text_query="coffee")
    url = "https://places.googleapis.com/v1/places:searchText"
    body = req.model_dump(by_alias=True, exclude={"field_mask"}, exclude_none=True)
    assert req._cache_key() == build_cache_key("POST", url, "places.id", body)


@pytest.fixture(autouse=True)
async def _close_client():
    yield
    await close_http_client()
