"""Routes API billing helpers (explicit per request subclass)."""

from __future__ import annotations

from gmaps.requests.sku import BillableSKU


def compute_routes_sku(
    *,
    routing_preference: str | None,
    intermediate_count: int,
    optimize_waypoint_order: bool,
) -> BillableSKU:
    """SKU for ``computeRoutes`` from routing options."""
    pref = (routing_preference or "").upper()
    advanced = pref in {"TRAFFIC_AWARE", "TRAFFIC_AWARE_OPTIMAL"}
    if intermediate_count > 10:
        advanced = True
    if optimize_waypoint_order:
        advanced = True
    return BillableSKU.ROUTES_COMPUTE_PRO if advanced else BillableSKU.ROUTES_COMPUTE_ESSENTIALS


def compute_route_matrix_sku(
    *,
    routing_preference: str | None,
    optimize_waypoint_order: bool,
) -> BillableSKU:
    """SKU for ``computeRouteMatrix`` from routing options."""
    pref = (routing_preference or "").upper()
    advanced = pref in {"TRAFFIC_AWARE", "TRAFFIC_AWARE_OPTIMAL"} or optimize_waypoint_order
    return BillableSKU.ROUTES_MATRIX_PRO if advanced else BillableSKU.ROUTES_MATRIX_ESSENTIALS


def matrix_element_units(origin_count: int, destination_count: int) -> int:
    """Billable matrix elements (origins × destinations)."""
    count = origin_count * destination_count
    return count if count > 0 else 1
