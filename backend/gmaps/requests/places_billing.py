"""Field-mask tier helpers for Places request billing (explicit per request class)."""

from __future__ import annotations

from gmaps.requests.sku import BillableSKU

_ENTERPRISE_ATMOSPHERE = frozenset(
    {
        "reviews",
        "reviewsummary",
        "editorialsummary",
        "generativesummary",
        "evchargeamenitysummary",
        "neighborhoodsummary",
    }
)
_ENTERPRISE = frozenset(
    {
        "rating",
        "userratingcount",
        "regularopeninghours",
        "currentopeninghours",
        "websiteuri",
        "nationalphonenumber",
        "internationalphonenumber",
        "pricelevel",
        "pricerange",
    }
)
_PRO = frozenset(
    {
        "displayname",
        "businessstatus",
        "primarytype",
        "googlemapsuri",
        "navigationpoints",
        "entrances",
    }
)


def place_details_sku(field_mask: str) -> BillableSKU:
    """Highest Place Details tier implied by ``field_mask``."""
    tokens = {part.strip().lower().split(".")[-1] for part in field_mask.split(",") if part.strip()}
    if tokens & _ENTERPRISE_ATMOSPHERE:
        return BillableSKU.PLACES_DETAILS_ENTERPRISE_ATMOSPHERE
    if tokens & _ENTERPRISE:
        return BillableSKU.PLACES_DETAILS_ENTERPRISE
    if tokens & _PRO:
        return BillableSKU.PLACES_DETAILS_PRO
    return BillableSKU.PLACES_DETAILS_ESSENTIALS


def text_search_sku(field_mask: str) -> BillableSKU:
    """Text search bills at the highest tier in the mask."""
    tier = place_details_sku(field_mask)
    if tier in {
        BillableSKU.PLACES_DETAILS_ENTERPRISE_ATMOSPHERE,
        BillableSKU.PLACES_DETAILS_ENTERPRISE,
    }:
        return tier
    return BillableSKU.PLACES_TEXT_SEARCH_PRO


def nearby_search_sku(field_mask: str) -> BillableSKU:
    """Nearby search bills at the highest tier in the mask."""
    tier = place_details_sku(field_mask)
    if tier in {
        BillableSKU.PLACES_DETAILS_ENTERPRISE_ATMOSPHERE,
        BillableSKU.PLACES_DETAILS_ENTERPRISE,
    }:
        return tier
    return BillableSKU.PLACES_NEARBY_SEARCH_PRO
