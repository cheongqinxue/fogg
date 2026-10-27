"""Places API (New) request classes."""

from __future__ import annotations

from typing import Any

import httpx
from pydantic import Field, field_validator

from gmaps.requests._google_json import GoogleJsonModel, LatLng
from gmaps.requests.base import GoogleMapRequest, get_http_client
from gmaps.requests.places_billing import nearby_search_sku, place_details_sku, text_search_sku
from gmaps.requests.sku import BillableSKU
from gmaps.response_cache import build_cache_key

PLACES_BASE = "https://places.googleapis.com"


class Circle(GoogleJsonModel):
    """Circular location restriction."""

    center: LatLng
    radius: float = Field(gt=0, description="Radius in meters.")


class LocationRestriction(GoogleJsonModel):
    """Nearby search region."""

    circle: Circle


class PlacesTextSearchRequest(GoogleMapRequest[dict[str, Any]]):
    """``POST /v1/places:searchText``."""

    field_mask: str = Field(min_length=1)
    text_query: str = Field(min_length=1)
    language_code: str | None = None
    region_code: str | None = None
    page_size: int = Field(default=10, ge=1, le=20)
    page_token: str | None = None
    included_type: str | None = None
    open_now: bool | None = None
    min_rating: float | None = Field(default=None, ge=0, le=5)

    @property
    def billable_sku(self) -> BillableSKU:
        return text_search_sku(self.field_mask)

    def _billable_for_attempt(self) -> list[tuple[BillableSKU, int]]:
        return [(self.billable_sku, 1)]

    def _cache_key(self) -> str:
        return build_cache_key(
            "POST",
            f"{PLACES_BASE}/v1/places:searchText",
            self.field_mask,
            self._body(),
        )

    def _body(self) -> dict[str, object]:
        return self.model_dump(
            by_alias=True,
            exclude={"field_mask"},
            exclude_none=True,
        )

    def _headers(self) -> dict[str, str]:
        headers = self._api_key_header()
        headers["X-Goog-FieldMask"] = self.field_mask
        headers["Content-Type"] = "application/json"
        return headers

    async def _do_http(self) -> httpx.Response:
        return await get_http_client().post(
            f"{PLACES_BASE}/v1/places:searchText",
            json=self._body(),
            headers=self._headers(),
        )


class PlacesSearchNearbyRequest(GoogleMapRequest[dict[str, Any]]):
    """``POST /v1/places:searchNearby``."""

    field_mask: str = Field(min_length=1)
    location_restriction: LocationRestriction
    included_types: list[str] = Field(min_length=1)
    max_result_count: int = Field(default=10, ge=1, le=20)
    language_code: str | None = None
    rank_preference: str | None = Field(
        default=None,
        pattern="^(DISTANCE|POPULARITY|RANK_PREFERENCE_UNSPECIFIED)?$",
    )

    @field_validator("included_types")
    @classmethod
    def validate_types_non_empty(cls, values: list[str]) -> list[str]:
        if not all(value.strip() for value in values):
            msg = "included_types entries must be non-empty"
            raise ValueError(msg)
        return values

    @property
    def billable_sku(self) -> BillableSKU:
        return nearby_search_sku(self.field_mask)

    def _billable_for_attempt(self) -> list[tuple[BillableSKU, int]]:
        return [(self.billable_sku, 1)]

    def _cache_key(self) -> str:
        return build_cache_key(
            "POST",
            f"{PLACES_BASE}/v1/places:searchNearby",
            self.field_mask,
            self._body(),
        )

    def _body(self) -> dict[str, object]:
        return self.model_dump(by_alias=True, exclude={"field_mask"}, exclude_none=True)

    def _headers(self) -> dict[str, str]:
        headers = self._api_key_header()
        headers["X-Goog-FieldMask"] = self.field_mask
        headers["Content-Type"] = "application/json"
        return headers

    async def _do_http(self) -> httpx.Response:
        return await get_http_client().post(
            f"{PLACES_BASE}/v1/places:searchNearby",
            json=self._body(),
            headers=self._headers(),
        )


class PlacesAutocompleteRequest(GoogleMapRequest[dict[str, Any]]):
    """``POST /v1/places:autocomplete``."""

    field_mask: str = Field(min_length=1)
    input: str = Field(min_length=1)
    language_code: str | None = None
    region_code: str | None = None
    session_token: str | None = None

    @property
    def billable_sku(self) -> BillableSKU:
        return BillableSKU.PLACES_AUTOCOMPLETE

    def _billable_for_attempt(self) -> list[tuple[BillableSKU, int]]:
        return [(BillableSKU.PLACES_AUTOCOMPLETE, 1)]

    def _cache_key(self) -> str:
        return build_cache_key(
            "POST",
            f"{PLACES_BASE}/v1/places:autocomplete",
            self.field_mask,
            self._body(),
        )

    def _body(self) -> dict[str, object]:
        return self.model_dump(by_alias=True, exclude={"field_mask"}, exclude_none=True)

    def _headers(self) -> dict[str, str]:
        headers = self._api_key_header()
        headers["X-Goog-FieldMask"] = self.field_mask
        headers["Content-Type"] = "application/json"
        return headers

    async def _do_http(self) -> httpx.Response:
        return await get_http_client().post(
            f"{PLACES_BASE}/v1/places:autocomplete",
            json=self._body(),
            headers=self._headers(),
        )


class PlacesGetRequest(GoogleMapRequest[dict[str, Any]]):
    """``GET /v1/places/{place_id}``."""

    field_mask: str = Field(min_length=1)
    place_id: str = Field(min_length=1)

    @property
    def billable_sku(self) -> BillableSKU:
        return place_details_sku(self.field_mask)

    def _billable_for_attempt(self) -> list[tuple[BillableSKU, int]]:
        return [(self.billable_sku, 1)]

    def _cache_key(self) -> str:
        return build_cache_key(
            "GET",
            f"{PLACES_BASE}/v1/places/{self.place_id}",
            self.field_mask,
            {},
        )

    def _headers(self) -> dict[str, str]:
        headers = self._api_key_header()
        headers["X-Goog-FieldMask"] = self.field_mask
        return headers

    async def _do_http(self) -> httpx.Response:
        return await get_http_client().get(
            f"{PLACES_BASE}/v1/places/{self.place_id}",
            headers=self._headers(),
        )
