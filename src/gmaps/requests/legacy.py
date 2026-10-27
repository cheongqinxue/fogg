"""Legacy Maps HTTP API request classes."""

from __future__ import annotations

from typing import Any

import httpx
from pydantic import Field, model_validator

from gmaps.requests.base import GoogleMapRequest, get_http_client
from gmaps.requests.sku import BillableSKU
from gmaps.response_cache import build_cache_key
from gmaps.settings import get_settings

MAPS_BASE = "https://maps.googleapis.com"


class GeocodeRequest(GoogleMapRequest[dict[str, Any]]):
    """``GET /maps/api/geocode/json``."""

    address: str | None = Field(default=None, min_length=1)
    latlng: str | None = Field(default=None, min_length=1)
    place_id: str | None = Field(default=None, min_length=1)
    language: str | None = None

    @model_validator(mode="after")
    def require_location_input(self) -> GeocodeRequest:
        if not (self.address or self.latlng or self.place_id):
            msg = "One of address, latlng, or place_id is required"
            raise ValueError(msg)
        return self

    @property
    def billable_sku(self) -> BillableSKU:
        return BillableSKU.GEOCODING

    def _billable_for_attempt(self) -> list[tuple[BillableSKU, int]]:
        return [(BillableSKU.GEOCODING, 1)]

    def _query_params(self) -> dict[str, str]:
        settings = get_settings()
        params = self.model_dump(exclude_none=True)
        params["key"] = settings.google_maps_api_key
        return {key: str(value) for key, value in params.items()}

    def _cache_key(self) -> str:
        params = self.model_dump(exclude_none=True)
        return build_cache_key(
            "GET",
            f"{MAPS_BASE}/maps/api/geocode/json",
            None,
            params,
        )

    async def _do_http(self) -> httpx.Response:
        return await get_http_client().get(
            f"{MAPS_BASE}/maps/api/geocode/json",
            params=self._query_params(),
        )


class DirectionsRequest(GoogleMapRequest[dict[str, Any]]):
    """``GET /maps/api/directions/json``."""

    origin: str = Field(min_length=1)
    destination: str = Field(min_length=1)
    mode: str | None = Field(default=None, pattern="^(driving|walking|bicycling|transit)?$")
    departure_time: str | None = None
    language: str | None = None

    @property
    def billable_sku(self) -> BillableSKU:
        return BillableSKU.DIRECTIONS_LEGACY

    def _billable_for_attempt(self) -> list[tuple[BillableSKU, int]]:
        return [(BillableSKU.DIRECTIONS_LEGACY, 1)]

    def _query_params(self) -> dict[str, str]:
        settings = get_settings()
        params = self.model_dump(exclude_none=True)
        params["key"] = settings.google_maps_api_key
        return {key: str(value) for key, value in params.items()}

    def _cache_key(self) -> str:
        params = self.model_dump(exclude_none=True)
        return build_cache_key(
            "GET",
            f"{MAPS_BASE}/maps/api/directions/json",
            None,
            params,
        )

    async def _do_http(self) -> httpx.Response:
        return await get_http_client().get(
            f"{MAPS_BASE}/maps/api/directions/json",
            params=self._query_params(),
        )
