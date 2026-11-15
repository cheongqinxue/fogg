"""Explicit Google Places Search fields through the Pro SKU (November 2026)."""

_COMMON = (
    "accessibilityOptions",
    "addressComponents",
    "addressDescriptor",
    "adrFormatAddress",
    "attributions",
    "businessStatus",
    "consumerAlert",
    "containingPlaces",
    "displayName",
    "entrances",
    "formattedAddress",
    "googleMapsLinks",
    "googleMapsTypeLabel",
    "googleMapsUri",
    "iconBackgroundColor",
    "iconMaskBaseUri",
    "id",
    "location",
    "name",
    "navigationPoints",
    "movedPlace",
    "movedPlaceId",
    "openingDate",
    "photos",
    "plusCode",
    "postalAddress",
    "primaryType",
    "primaryTypeDisplayName",
    "pureServiceAreaBusiness",
    "shortFormattedAddress",
    "subDestinations",
    "timeZone",
    "types",
    "utcOffsetMinutes",
    "viewport",
)

NEARBY_SEARCH_PRO_FIELDS = _COMMON
TEXT_SEARCH_PRO_FIELDS = (*_COMMON, "searchUri")
NEARBY_SEARCH_PRO_MASK = ",".join(f"places.{field}" for field in NEARBY_SEARCH_PRO_FIELDS)
TEXT_SEARCH_PRO_MASK = (
    ",".join(f"places.{field}" for field in TEXT_SEARCH_PRO_FIELDS) + ",nextPageToken"
)
PLACE_DETAILS_PRO_MASK = ",".join(_COMMON)
