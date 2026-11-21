"""Tests for GoogleMapRequest subclasses (cache, quota, retry)."""

import logging

import httpx
import pytest
import fakeredis.aioredis
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError
from pydantic import ValidationError
from pytest import LogCaptureFixture
from tenacity import wait_fixed

from gmaps.errors import GmapsQuotaExceededError, GoogleMapsApiError
from gmaps.quota.caps import SKU_FREE_CAP
from gmaps.quota.store import RedisUsageStore
from gmaps.quota.types import BillableEvent
from utils.redis_client import set_async_redis_client_for_tests
from gmaps.requests import (
    PlacesAutocompleteRequest,
    PlacesGetRequest,
    PlacesSearchNearbyRequest,
    PlacesTextSearchRequest,
    QuotaBalance,
    RoutesComputeRouteMatrixRequest,
    RoutesComputeRoutesRequest,
)
from gmaps.requests.places import Circle, LocationRestriction
from gmaps.requests.places_billing import place_details_sku, text_search_sku
from gmaps.requests.routes import RouteMatrixWaypoint, Waypoint
from gmaps.requests.sku import BillableSKU
from gmaps.requests._google_json import LatLng
from gmaps.requests.base import (
    close_http_client,
    get_http_client,
    requests_base_max_attempts,
    requests_base_max_retries,
)
from gmaps.response_cache import build_cache_key
from utils.settings import get_settings
from gmaps.quota.store import reset_usage_store_for_tests

BASE_LOGGER = "gmaps.requests.base"


@pytest.mark.asyncio
async def test_text_search_circle_restriction_filters_outside_and_requests_location(monkeypatch):
    import json
    from gmaps.tools import places_text_search
    from gmaps.requests.search_fields import TEXT_SEARCH_PRO_MASK
    from gmaps.requests.places import PlacesTextSearchRequest

    seen = []

    async def fake_call(request):
        seen.append(request)
        return {
            "places": [
                {"id": "inside", "location": {"latitude": 36.65, "longitude": 138.18}},
                {"id": "outside", "location": {"latitude": 37.0, "longitude": 138.18}},
            ]
        }

    monkeypatch.setattr(PlacesTextSearchRequest, "call", fake_call)
    result = json.loads(
        await places_text_search.ainvoke(
            {
                "text_query": "ski resorts",
                "priority": 1,
                "area": {
                    "latitude": 36.6513,
                    "longitude": 138.181,
                    "radius_meters": 20000,
                    "mode": "restrict",
                },
            }
        )
    )
    assert [place["id"] for place in result["places"]] == ["inside"]
    assert seen[0].field_mask == TEXT_SEARCH_PRO_MASK
    assert "locationRestriction" in seen[0]._body()


@pytest.mark.asyncio
async def test_agent_search_tools_use_pro_masks(monkeypatch):
    from gmaps.tools import places_search_nearby, places_text_search
    from gmaps.requests.places import PlacesSearchNearbyRequest, PlacesTextSearchRequest
    from gmaps.requests.search_fields import NEARBY_SEARCH_PRO_MASK, TEXT_SEARCH_PRO_MASK

    captured = []

    async def fake_call(request):
        captured.append(request)
        return {"places": []}

    monkeypatch.setattr(PlacesTextSearchRequest, "call", fake_call)
    monkeypatch.setattr(PlacesSearchNearbyRequest, "call", fake_call)
    assert "field_mask" not in places_text_search.args
    assert "field_mask" not in places_search_nearby.args
    await places_text_search.ainvoke({"text_query": "coffee", "priority": 1})
    await places_search_nearby.ainvoke(
        {
            "latitude": 36.65,
            "longitude": 138.18,
            "radius_meters": 5000,
            "included_types": ["cafe"],
            "priority": 1,
        }
    )
    assert [request.field_mask for request in captured] == [
        TEXT_SEARCH_PRO_MASK,
        NEARBY_SEARCH_PRO_MASK,
    ]
    assert [request.billable_sku for request in captured] == [
        BillableSKU.PLACES_TEXT_SEARCH_PRO,
        BillableSKU.PLACES_NEARBY_SEARCH_PRO,
    ]
    for mask in (TEXT_SEARCH_PRO_MASK, NEARBY_SEARCH_PRO_MASK):
        fields = set(mask.split(","))
        assert {
            "places.id",
            "places.displayName",
            "places.location",
            "places.entrances",
            "places.navigationPoints",
        } <= fields
        assert not {"places.rating", "places.reviews", "*"} & fields
    assert "textQuery" in captured[0]._body()
    assert "locationRestriction" in captured[1]._body()
    assert "includedTypes" in captured[1]._body()


@pytest.mark.asyncio
async def test_all_agent_tools_hide_masks_and_use_code_owned_fields(monkeypatch):
    from master.tools import get_tools
    from gmaps.tools import places_get, routes_compute, routes_compute_matrix
    from gmaps.requests.places import PlacesGetRequest
    from gmaps.requests.route_fields import MATRIX_MASK, ROUTE_MASK, ROUTE_OPTIMIZED_ORDER_FIELD
    from gmaps.requests.search_fields import PLACE_DETAILS_PRO_MASK
    from gmaps.requests.routes import RoutesComputeRoutesRequest, RoutesComputeRouteMatrixRequest

    captured = []

    async def fake_call(request):
        captured.append(request)
        return {}

    for cls in (PlacesGetRequest, RoutesComputeRoutesRequest, RoutesComputeRouteMatrixRequest):
        monkeypatch.setattr(cls, "call", fake_call)
    assert all("field_mask" not in tool.args for tool in get_tools())
    await places_get.ainvoke({"place_id": "sample", "priority": 1})
    waypoint = {"latitude": 36.65, "longitude": 138.18}
    await routes_compute.ainvoke({"origin": waypoint, "destination": waypoint, "priority": 1})
    await routes_compute.ainvoke(
        {
            "origin": waypoint,
            "destination": waypoint,
            "optimize_waypoint_order": True,
            "priority": 1,
        }
    )
    await routes_compute_matrix.ainvoke(
        {"origins": [waypoint], "destinations": [waypoint], "priority": 1}
    )
    assert [item.field_mask for item in captured] == [
        PLACE_DETAILS_PRO_MASK,
        ROUTE_MASK,
        f"{ROUTE_MASK},{ROUTE_OPTIMIZED_ORDER_FIELD}",
        MATRIX_MASK,
    ]
    assert [item.billable_sku for item in captured] == [
        BillableSKU.PLACES_DETAILS_PRO,
        BillableSKU.ROUTES_COMPUTE_ESSENTIALS,
        BillableSKU.ROUTES_COMPUTE_PRO,
        BillableSKU.ROUTES_MATRIX_ESSENTIALS,
    ]
    assert {
        "routes.legs.steps.navigationInstruction",
        "routes.legs.startLocation",
        "routes.legs.steps.polyline.encodedPolyline",
    } <= set(ROUTE_MASK.split(","))
    assert not any(
        "tollInfo" in field or "speedReadingIntervals" in field for field in ROUTE_MASK.split(",")
    )
    assert "travelMode" in captured[1]._body()
    assert "travelMode" in captured[3]._body()


def test_maps_cache_and_quota_use_shared_redis_url(monkeypatch):
    from gmaps import response_cache

    reset_usage_store_for_tests()
    monkeypatch.setenv("REDIS_URL", "redis://localhost:16379/9")
    monkeypatch.setenv("GMAPS_REDIS_URL", "redis://localhost:6379/0")
    captured = []
    monkeypatch.setattr(
        "utils.redis_client.get_async_redis_client",
        lambda url: captured.append(url) or object(),
    )
    try:
        assert get_settings().redis_url == "redis://localhost:16379/9"
        assert response_cache._get_cache().redis_url == "redis://localhost:16379/9"
        RedisUsageStore()
        assert captured == ["redis://localhost:16379/9"]
    finally:
        reset_usage_store_for_tests()


@pytest.mark.asyncio
@pytest.mark.parametrize("enforce", ["true", "false"])
@pytest.mark.parametrize("failure", [RedisConnectionError, RedisTimeoutError])
async def test_redis_quota_outage_allows_mocked_request(monkeypatch, caplog, enforce, failure):
    reset_usage_store_for_tests()
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "test-key")
    monkeypatch.setenv("GMAPS_CACHE_ENABLED", "false")
    monkeypatch.setenv("GMAPS_QUOTA_TRACKING", "true")
    monkeypatch.setenv("GMAPS_QUOTA_ENFORCE", enforce)

    class UnavailableStore:
        async def try_reserve(self, *_args, **_kwargs):
            raise failure("offline")

        async def record(self, *_args, **_kwargs):
            raise failure("offline")

    async def fake_post(*_args, **_kwargs):
        return httpx.Response(
            200, request=httpx.Request("POST", "https://example.com"), json={"places": []}
        )

    monkeypatch.setattr("gmaps.requests.base.get_usage_store", lambda: UnavailableStore())
    monkeypatch.setattr(get_http_client(), "post", fake_post)
    result = await PlacesTextSearchRequest(field_mask="places.id", text_query="coffee").call()
    assert result == {"places": []}
    assert "without reliable quota enforcement" in caplog.text
    reset_usage_store_for_tests()


@pytest.mark.asyncio
async def test_quota_refund_outage_preserves_original_http_failure(monkeypatch, caplog):
    reset_usage_store_for_tests()
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "test-key")
    monkeypatch.setenv("GMAPS_CACHE_ENABLED", "false")
    monkeypatch.setenv("GMAPS_QUOTA_TRACKING", "true")
    monkeypatch.setenv("GMAPS_QUOTA_ENFORCE", "false")
    monkeypatch.setenv("GMAPS_REQUESTS_BASE_MAX_RETRIES", "0")

    class Store:
        async def record(self, *_args, **_kwargs):
            pass

        async def refund(self, *_args, **_kwargs):
            raise RedisConnectionError("redis offline")

    async def fake_post(*_args, **_kwargs):
        raise httpx.ConnectError("maps connection failed")

    monkeypatch.setattr("gmaps.requests.base.get_usage_store", lambda: Store())
    monkeypatch.setattr(get_http_client(), "post", fake_post)
    with pytest.raises(GoogleMapsApiError, match="maps connection failed"):
        await PlacesTextSearchRequest(field_mask="places.id", text_query="coffee").call()
    assert "quota refund failed" in caplog.text
    reset_usage_store_for_tests()


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
    set_async_redis_client_for_tests(fake)
    store = RedisUsageStore(fake)
    cap = SKU_FREE_CAP["places_text_search_pro"]
    assert cap is not None
    await store.try_reserve([BillableEvent("places_text_search_pro", 100)])

    req = PlacesTextSearchRequest(field_mask="places.displayName", text_query="x")
    balance = await req.check_quota()
    assert balance == QuotaBalance(used=100, balance=cap - 100)
    reset_usage_store_for_tests()
    set_async_redis_client_for_tests(None)


@pytest.mark.asyncio
async def test_cache_hit_skips_http_and_quota(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reset_usage_store_for_tests()
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "test-key")
    monkeypatch.setenv("GMAPS_CACHE_ENABLED", "true")
    monkeypatch.setenv("GMAPS_QUOTA_TRACKING", "true")
    fake = fakeredis.aioredis.FakeRedis(decode_responses=True)
    set_async_redis_client_for_tests(fake)
    calls = {"n": 0}

    async def fake_post(*_args, **_kwargs):
        calls["n"] += 1
        request = httpx.Request("POST", "https://example.com")
        return httpx.Response(200, request=request, json={"places": [{"id": "a"}]})

    monkeypatch.setattr(get_http_client(), "post", fake_post)
    req = PlacesTextSearchRequest(field_mask="places.displayName", text_query="coffee")
    first = await req.call()
    second = await req.call()
    assert first == second
    assert calls["n"] == 1
    store = RedisUsageStore(fake)
    totals = await store.totals()
    assert totals.get("places_text_search_pro") == 1
    reset_usage_store_for_tests()
    set_async_redis_client_for_tests(None)


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
    set_async_redis_client_for_tests(fake)
    calls = {"n": 0}

    async def fake_post(*_args, **_kwargs):
        calls["n"] += 1
        request = httpx.Request("POST", "https://example.com")
        if calls["n"] < 3:
            return httpx.Response(503, request=request, text="busy")
        return httpx.Response(200, request=request, json={"places": []})

    monkeypatch.setattr(get_http_client(), "post", fake_post)
    req = PlacesTextSearchRequest(field_mask="places.displayName", text_query="coffee")
    await req.call()
    assert calls["n"] == 3
    store = RedisUsageStore(fake)
    assert store and (await store.totals()).get("places_text_search_pro") == 3
    reset_usage_store_for_tests()
    set_async_redis_client_for_tests(None)


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
    set_async_redis_client_for_tests(fake)
    store = RedisUsageStore(fake)
    cap = SKU_FREE_CAP["places_text_search_pro"]
    assert cap is not None
    await store.try_reserve([BillableEvent("places_text_search_pro", cap)])
    calls = {"n": 0}

    async def fake_post(*_args, **_kwargs):
        calls["n"] += 1
        return httpx.Response(200, request=httpx.Request("POST", "https://x"), json={})

    monkeypatch.setattr(get_http_client(), "post", fake_post)
    req = PlacesTextSearchRequest(field_mask="places.displayName", text_query="coffee")
    with pytest.raises(GmapsQuotaExceededError):
        await req.call()
    assert calls["n"] == 0
    reset_usage_store_for_tests()
    set_async_redis_client_for_tests(None)


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
    set_async_redis_client_for_tests(fake)

    async def fake_post(*_args, **_kwargs):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(get_http_client(), "post", fake_post)
    req = PlacesTextSearchRequest(field_mask="places.displayName", text_query="coffee")
    with pytest.raises(GoogleMapsApiError):
        await req.call()
    store = RedisUsageStore(fake)
    assert (await store.totals()).get("places_text_search_pro", 0) == 0
    reset_usage_store_for_tests()
    set_async_redis_client_for_tests(None)


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
    set_async_redis_client_for_tests(fake)

    async def fake_post(*_args, **_kwargs):
        request = httpx.Request("POST", "https://example.com")
        return httpx.Response(400, request=request, text="bad")

    monkeypatch.setattr(get_http_client(), "post", fake_post)
    req = PlacesTextSearchRequest(field_mask="places.displayName", text_query="coffee")
    with pytest.raises(GoogleMapsApiError):
        await req.call()
    store = RedisUsageStore(fake)
    assert (await store.totals()).get("places_text_search_pro") == 1
    reset_usage_store_for_tests()
    set_async_redis_client_for_tests(None)


@pytest.mark.asyncio
async def test_ambiguous_read_timeout_keeps_quota(
    monkeypatch: pytest.MonkeyPatch,
    fast_retry: None,
) -> None:
    reset_usage_store_for_tests()
    monkeypatch.setenv("GMAPS_QUOTA_ENFORCE", "true")
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "test-key")
    monkeypatch.setenv("GMAPS_CACHE_ENABLED", "false")
    fake = fakeredis.aioredis.FakeRedis(decode_responses=True)
    set_async_redis_client_for_tests(fake)

    async def fake_post(*_args, **_kwargs):
        raise httpx.ReadTimeout("response timed out")

    monkeypatch.setattr(get_http_client(), "post", fake_post)
    req = PlacesTextSearchRequest(field_mask="places.displayName", text_query="coffee")
    with pytest.raises(GoogleMapsApiError):
        await req.call()
    store = RedisUsageStore(fake)
    # A read timeout can happen after Google processed the request.
    assert (await store.totals()).get("places_text_search_pro") == requests_base_max_attempts()
    reset_usage_store_for_tests()
    set_async_redis_client_for_tests(None)


@pytest.mark.asyncio
async def test_daily_usage_tracks_same_reservations_as_monthly() -> None:
    fake = fakeredis.aioredis.FakeRedis(decode_responses=True)
    store = RedisUsageStore(fake)
    await store.try_reserve(
        [BillableEvent("routes_matrix_essentials", 6)],
        period="2026-11",
        day="2026-11-14",
    )
    assert await store.totals("2026-11") == {"routes_matrix_essentials": 6}
    assert await store.daily_totals("2026-11-14") == {"routes_matrix_essentials": 6}


@pytest.mark.asyncio
async def test_unknown_sku_fails_closed_before_reservation() -> None:
    fake = fakeredis.aioredis.FakeRedis(decode_responses=True)
    store = RedisUsageStore(fake)
    with pytest.raises(ValueError, match="no verified free cap"):
        await store.try_reserve([BillableEvent("unclassified_sku", 1)])
    assert await store.totals() == {}


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
    monkeypatch.setenv("GMAPS_QUOTA_ENFORCE", "false")
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
            BillableSKU.PLACES_TEXT_SEARCH_IDS_ONLY,
        ),
        (
            PlacesAutocompleteRequest(field_mask="suggestions.placePrediction", input="a"),
            BillableSKU.PLACES_AUTOCOMPLETE,
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


def test_places_field_masks_use_correct_sku_boundaries() -> None:
    assert text_search_sku("places.id,places.name") == BillableSKU.PLACES_TEXT_SEARCH_IDS_ONLY
    assert text_search_sku("places.photos") == BillableSKU.PLACES_TEXT_SEARCH_PRO
    assert place_details_sku("photos") == BillableSKU.PLACES_DETAILS_IDS_ONLY
    assert text_search_sku("places.*") == BillableSKU.PLACES_TEXT_SEARCH_ENTERPRISE_ATMOSPHERE


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


def test_two_wheeler_routes_use_enterprise_caps() -> None:
    origin, destination = _tokyo_osaka_routes()
    routes = RoutesComputeRoutesRequest(
        field_mask="routes.duration",
        origin=origin,
        destination=destination,
        travel_mode="TWO_WHEELER",
    )
    matrix = RoutesComputeRouteMatrixRequest(
        field_mask="routes.duration",
        origins=[RouteMatrixWaypoint(waypoint=origin)],
        destinations=[RouteMatrixWaypoint(waypoint=destination)],
        travel_mode="TWO_WHEELER",
    )
    assert routes.billable_sku == BillableSKU.ROUTES_COMPUTE_ENTERPRISE
    assert matrix._billable_for_attempt() == [(BillableSKU.ROUTES_MATRIX_ENTERPRISE, 1)]


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
