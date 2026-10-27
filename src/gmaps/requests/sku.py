"""Billable SKU identifiers for local quota caps."""

from __future__ import annotations

from enum import StrEnum


class BillableSKU(StrEnum):
    """Internal SKU keys aligned with ``quota.caps.SKU_FREE_CAP``."""

    PLACES_TEXT_SEARCH_PRO = "places_text_search_pro"
    PLACES_NEARBY_SEARCH_PRO = "places_nearby_search_pro"
    PLACES_AUTOCOMPLETE = "places_autocomplete"
    PLACES_DETAILS_ESSENTIALS = "places_details_essentials"
    PLACES_DETAILS_PRO = "places_details_pro"
    PLACES_DETAILS_ENTERPRISE = "places_details_enterprise"
    PLACES_DETAILS_ENTERPRISE_ATMOSPHERE = "places_details_enterprise_atmosphere"
    ROUTES_COMPUTE_ESSENTIALS = "routes_compute_essentials"
    ROUTES_COMPUTE_PRO = "routes_compute_pro"
    ROUTES_MATRIX_ESSENTIALS = "routes_matrix_essentials"
    ROUTES_MATRIX_PRO = "routes_matrix_pro"
    GEOCODING = "geocoding"
    DIRECTIONS_LEGACY = "directions_legacy"
