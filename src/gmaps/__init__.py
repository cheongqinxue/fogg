"""In-process Google Maps client (request-class API)."""

from gmaps.errors import GmapsQuotaExceededError, GoogleMapsApiError
from gmaps.requests import (
    BillableSKU,
    DirectionsRequest,
    GeocodeRequest,
    PlacesAutocompleteRequest,
    PlacesGetRequest,
    PlacesSearchNearbyRequest,
    PlacesTextSearchRequest,
    QuotaBalance,
    RoutesComputeRouteMatrixRequest,
    RoutesComputeRoutesRequest,
)
from gmaps.requests.base import close_http_client

__all__ = [
    "BillableSKU",
    "DirectionsRequest",
    "GeocodeRequest",
    "GmapsQuotaExceededError",
    "GoogleMapsApiError",
    "PlacesAutocompleteRequest",
    "PlacesGetRequest",
    "PlacesSearchNearbyRequest",
    "PlacesTextSearchRequest",
    "QuotaBalance",
    "RoutesComputeRouteMatrixRequest",
    "RoutesComputeRoutesRequest",
    "close_http_client",
]
