"""Monthly free-tier caps per internal SKU key."""

from __future__ import annotations

SKU_FREE_CAP: dict[str, int | None] = {
    "places_text_search_pro": 5_000,
    "places_nearby_search_pro": 5_000,
    "places_autocomplete": 10_000,
    "places_details_essentials": 10_000,
    "places_details_pro": 5_000,
    "places_details_enterprise": 1_000,
    "places_details_enterprise_atmosphere": 1_000,
    "places_photos": 1_000,
    "routes_compute_essentials": 10_000,
    "routes_compute_pro": 5_000,
    "routes_matrix_essentials": 10_000,
    "routes_matrix_pro": 5_000,
    "geocoding": 10_000,
    "directions_legacy": 10_000,
    "distance_matrix_legacy": 10_000,
    "legacy_places_nearby": 5_000,
    "legacy_places_text": 5_000,
    "legacy_places_details": 5_000,
    "legacy_autocomplete": 10_000,
    "unknown": None,
}
