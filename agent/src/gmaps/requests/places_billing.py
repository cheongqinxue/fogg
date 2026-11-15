"""Conservative Places SKU classification from response field masks."""

from __future__ import annotations

from gmaps.requests.sku import BillableSKU

_IDS_ONLY = frozenset(
    {
        "attributions",
        "consumeralert",
        "id",
        "movedplace",
        "movedplaceid",
        "name",
        "nextpagetoken",
    }
)
_DETAILS_IDS_ONLY = _IDS_ONLY | {"photos"}
_TEXT_IDS_ONLY = _IDS_ONLY - {"photos"}

_TEXT_NEARBY_PRO = frozenset(
    {
        "accessibilityoptions",
        "addresscomponents",
        "addressdescriptor",
        "adrformataddress",
        "businessstatus",
        "containingplaces",
        "displayname",
        "entrances",
        "formattedaddress",
        "googlemapslinks",
        "googlemapstypelabel",
        "googlemapsuri",
        "iconbackgroundcolor",
        "iconmaskbaseuri",
        "id",
        "location",
        "navigationpoints",
        "openingdate",
        "photos",
        "pluscode",
        "postaladdress",
        "primarytype",
        "primarytypedisplayname",
        "pureserviceareabusiness",
        "searchuri",
        "shortformattedaddress",
        "subdestinations",
        "timezone",
        "types",
        "utcoffsetminutes",
        "viewport",
    }
)

_DETAILS_ESSENTIALS = frozenset(
    {
        "addresscomponents",
        "addressdescriptor",
        "adrformataddress",
        "formattedaddress",
        "location",
        "pluscode",
        "postaladdress",
        "shortformattedaddress",
        "types",
        "viewport",
    }
)
_DETAILS_PRO = frozenset(
    {
        "accessibilityoptions",
        "businessstatus",
        "containingplaces",
        "displayname",
        "entrances",
        "navigationpoints",
        "googlemapslinks",
        "googlemapstypelabel",
        "googlemapsuri",
        "iconbackgroundcolor",
        "iconmaskbaseuri",
        "openingdate",
        "primarytype",
        "primarytypedisplayname",
        "pureserviceareabusiness",
        "subdestinations",
        "timezone",
        "utcoffsetminutes",
    }
)

_ENTERPRISE = frozenset(
    {
        "currentopeninghours",
        "currentsecondaryopeninghours",
        "internationalphonenumber",
        "nationalphonenumber",
        "pricelevel",
        "pricerange",
        "rating",
        "regularopeninghours",
        "regularsecondaryopeninghours",
        "transitstation",
        "userratingcount",
        "websiteuri",
    }
)
_ENTERPRISE_ATMOSPHERE = frozenset(
    {
        "allowsdogs",
        "curbsidepickup",
        "delivery",
        "dinein",
        "editorialsummary",
        "evchargeamenitysummary",
        "evchargeoptions",
        "fueloptions",
        "goodforchildren",
        "goodforgroups",
        "goodforwatchingsports",
        "hascurbsidepickup",
        "hasdelivery",
        "hasdinein",
        "haslivemusic",
        "hasmenuforchildren",
        "hasoutdoorseating",
        "hasrestroom",
        "hastakeout",
        "haswifi",
        "isgoodforchildren",
        "isgoodforgroups",
        "isgoodforwatchingsports",
        "isreservable",
        "livemusic",
        "menuforchildren",
        "neighborhoodsummary",
        "outdoorseating",
        "parkingoptions",
        "paymentoptions",
        "reservable",
        "restroom",
        "reviews",
        "reviewsummary",
        "routingsummaries",
        "servesbeer",
        "servesbreakfast",
        "servesbrunch",
        "servescocktails",
        "servescoffee",
        "servesdessert",
        "servesdinner",
        "serveslunch",
        "servesvegetarianfood",
        "serveswine",
        "takeout",
    }
)

_KNOWN_TEXT_NEARBY_FIELDS = _IDS_ONLY | _TEXT_NEARBY_PRO | _ENTERPRISE | _ENTERPRISE_ATMOSPHERE
_KNOWN_DETAILS_FIELDS = (
    _DETAILS_IDS_ONLY | _DETAILS_ESSENTIALS | _DETAILS_PRO | _ENTERPRISE | _ENTERPRISE_ATMOSPHERE
)


def _mask_tokens(field_mask: str, *, places_prefix: bool = False) -> set[str]:
    """Extract selected top-level fields, retaining unknowns for fail-closed billing."""
    tokens: set[str] = set()
    for path in field_mask.split(","):
        parts = [part.strip().casefold() for part in path.split(".") if part.strip()]
        if places_prefix and parts and parts[0] == "places":
            parts = parts[1:]
        if parts:
            tokens.add(parts[0])
    return tokens


def _has_wildcard(tokens: set[str]) -> bool:
    return not tokens or "*" in tokens or "all" in tokens


def place_details_sku(field_mask: str) -> BillableSKU:
    """Return the highest Place Details SKU implied by the mask."""
    tokens = _mask_tokens(field_mask)
    if tokens and tokens <= _DETAILS_IDS_ONLY:
        return BillableSKU.PLACES_DETAILS_IDS_ONLY
    if _has_wildcard(tokens) or tokens - _KNOWN_DETAILS_FIELDS:
        return BillableSKU.PLACES_DETAILS_ENTERPRISE_ATMOSPHERE
    if tokens & _ENTERPRISE_ATMOSPHERE:
        return BillableSKU.PLACES_DETAILS_ENTERPRISE_ATMOSPHERE
    if tokens & _ENTERPRISE:
        return BillableSKU.PLACES_DETAILS_ENTERPRISE
    if tokens & _DETAILS_PRO:
        return BillableSKU.PLACES_DETAILS_PRO
    return BillableSKU.PLACES_DETAILS_ESSENTIALS


def text_search_sku(field_mask: str) -> BillableSKU:
    """Return the Text Search SKU; only identifier-only masks use IDs Only."""
    tokens = _mask_tokens(field_mask, places_prefix=True)
    if tokens and tokens <= _TEXT_IDS_ONLY:
        return BillableSKU.PLACES_TEXT_SEARCH_IDS_ONLY
    if _has_wildcard(tokens) or tokens - _KNOWN_TEXT_NEARBY_FIELDS:
        return BillableSKU.PLACES_TEXT_SEARCH_ENTERPRISE_ATMOSPHERE
    if tokens & _ENTERPRISE_ATMOSPHERE:
        return BillableSKU.PLACES_TEXT_SEARCH_ENTERPRISE_ATMOSPHERE
    if tokens & _ENTERPRISE:
        return BillableSKU.PLACES_TEXT_SEARCH_ENTERPRISE
    return BillableSKU.PLACES_TEXT_SEARCH_PRO


def nearby_search_sku(field_mask: str) -> BillableSKU:
    """Return the Nearby Search SKU; Nearby Search has no IDs-only SKU."""
    tokens = _mask_tokens(field_mask, places_prefix=True)
    if _has_wildcard(tokens) or tokens - _KNOWN_TEXT_NEARBY_FIELDS:
        return BillableSKU.PLACES_NEARBY_SEARCH_ENTERPRISE_ATMOSPHERE
    if tokens & _ENTERPRISE_ATMOSPHERE:
        return BillableSKU.PLACES_NEARBY_SEARCH_ENTERPRISE_ATMOSPHERE
    if tokens & _ENTERPRISE:
        return BillableSKU.PLACES_NEARBY_SEARCH_ENTERPRISE
    return BillableSKU.PLACES_NEARBY_SEARCH_PRO
