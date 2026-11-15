"""Monthly free-tier caps per internal SKU key."""

from __future__ import annotations

SKU_FREE_CAP: dict[str, int | None] = {
    "places_text_search_ids_only": None,
    "places_text_search_pro": 5_000,
    "places_text_search_enterprise": 1_000,
    "places_text_search_enterprise_atmosphere": 1_000,
    "places_nearby_search_pro": 5_000,
    "places_nearby_search_enterprise": 1_000,
    "places_nearby_search_enterprise_atmosphere": 1_000,
    "places_autocomplete": 10_000,
    "places_details_ids_only": None,
    "places_details_essentials": 10_000,
    "places_details_pro": 5_000,
    "places_details_enterprise": 1_000,
    "places_details_enterprise_atmosphere": 1_000,
    "routes_compute_essentials": 10_000,
    "routes_compute_pro": 5_000,
    "routes_compute_enterprise": 1_000,
    "routes_matrix_essentials": 10_000,
    "routes_matrix_pro": 5_000,
    "routes_matrix_enterprise": 1_000,
}
