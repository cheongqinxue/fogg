"""Routes API v2 request classes."""

from __future__ import annotations

from typing import Any

import httpx
from pydantic import ConfigDict, Field
from pydantic.alias_generators import to_camel

from gmaps.requests._google_json import GoogleJsonModel, LatLng
from gmaps.requests.base import GoogleMapRequest, get_http_client
from gmaps.requests.routes_billing import (
    compute_route_matrix_sku,
    compute_routes_sku,
    matrix_element_units,
)
from gmaps.requests.sku import BillableSKU
from gmaps.response_cache import build_cache_key

ROUTES_BASE = "https://routes.googleapis.com"


class Location(GoogleJsonModel):
    """Waypoint location."""

    lat_lng: LatLng | None = None


class Waypoint(GoogleJsonModel):
    """Route endpoint or via point."""

    location: Location | None = None
    place_id: str | None = None
    address: str | None = None


class RouteMatrixWaypoint(GoogleJsonModel):
    """Matrix origin/destination wrapper."""

    waypoint: Waypoint


class RoutesComputeRoutesRequest(GoogleMapRequest[dict[str, Any]]):
    """``POST /directions/v2:computeRoutes``."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True, alias_generator=to_camel)
    field_mask: str = Field(min_length=1)
    origin: Waypoint
    destination: Waypoint
    intermediates: list[Waypoint] = Field(default_factory=list)
    travel_mode: str = Field(default="DRIVE")
    routing_preference: str | None = Field(default="TRAFFIC_UNAWARE")
    compute_alternative_routes: bool = False
    optimize_waypoint_order: bool = False
    language_code: str = Field(default="en-US")
    units: str = Field(default="METRIC")

    @property
    def billable_sku(self) -> BillableSKU:
        return compute_routes_sku(
            routing_preference=self.routing_preference,
            travel_mode=self.travel_mode,
            intermediate_count=len(self.intermediates),
            optimize_waypoint_order=self.optimize_waypoint_order,
        )

    def _billable_for_attempt(self) -> list[tuple[BillableSKU, int]]:
        return [(self.billable_sku, 1)]

    def _cache_key(self) -> str:
        return build_cache_key(
            "POST",
            f"{ROUTES_BASE}/directions/v2:computeRoutes",
            self.field_mask,
            self._body(),
        )

    def _body(self) -> dict[str, object]:
        return self.model_dump(by_alias=True, exclude={"field_mask"}, exclude_none=True)

    async def _headers(self) -> dict[str, str]:
        headers = await self._api_key_header()
        headers["X-Goog-FieldMask"] = self.field_mask
        headers["Content-Type"] = "application/json"
        return headers

    async def _do_http(self) -> httpx.Response:
        return await get_http_client().post(
            f"{ROUTES_BASE}/directions/v2:computeRoutes",
            json=self._body(),
            headers=await self._headers(),
        )


class RoutesComputeRouteMatrixRequest(GoogleMapRequest[dict[str, Any]]):
    """``POST /distanceMatrix/v2:computeRouteMatrix``."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True, alias_generator=to_camel)
    field_mask: str = Field(min_length=1)
    origins: list[RouteMatrixWaypoint] = Field(min_length=1)
    destinations: list[RouteMatrixWaypoint] = Field(min_length=1)
    travel_mode: str = Field(default="DRIVE")
    routing_preference: str | None = None

    @property
    def billable_sku(self) -> BillableSKU:
        return compute_route_matrix_sku(
            routing_preference=self.routing_preference,
            travel_mode=self.travel_mode,
        )

    def _billable_for_attempt(self) -> list[tuple[BillableSKU, int]]:
        units = matrix_element_units(len(self.origins), len(self.destinations))
        return [(self.billable_sku, units)]

    def _cache_key(self) -> str:
        return build_cache_key(
            "POST",
            f"{ROUTES_BASE}/distanceMatrix/v2:computeRouteMatrix",
            self.field_mask,
            self._body(),
        )

    def _body(self) -> dict[str, object]:
        return self.model_dump(by_alias=True, exclude={"field_mask"}, exclude_none=True)

    async def _headers(self) -> dict[str, str]:
        headers = await self._api_key_header()
        headers["X-Goog-FieldMask"] = self.field_mask
        headers["Content-Type"] = "application/json"
        return headers

    async def _do_http(self) -> httpx.Response:
        return await get_http_client().post(
            f"{ROUTES_BASE}/distanceMatrix/v2:computeRouteMatrix",
            json=self._body(),
            headers=await self._headers(),
        )
