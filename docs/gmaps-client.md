# In-process Google Maps client (`gmaps`)

Each Google operation is a **request class** subclassing `GoogleMapRequest[TResponse]`. Build the model, then:

```python
from gmaps import PlacesTextSearchRequest

req = PlacesTextSearchRequest(
    field_mask="places.id,places.displayName",
    text_query="specialty coffee in Kyoto",
    page_size=10,
)
result = await req.call()
quota = await req.check_quota()  # QuotaBalance(used=..., balance=...)
```

## Request classes

| Class | Google API |
|-------|------------|
| `PlacesTextSearchRequest` | Places text search |
| `PlacesSearchNearbyRequest` | Nearby search |
| `PlacesAutocompleteRequest` | Autocomplete |
| `PlacesGetRequest` | Place details |
| `RoutesComputeRoutesRequest` | Routes computeRoutes |
| `RoutesComputeRouteMatrixRequest` | Route matrix |
| `GeocodeRequest` | Geocoding (legacy) |
| `DirectionsRequest` | Directions (legacy) |

Each class declares **billable SKUs and units** in `_billable_for_attempt()` (not inferred from URL paths). `billable_sku` is the primary SKU for `check_quota()`.

## Pipeline (on `call()`)

1. **Cache** — hit returns JSON with no HTTP and no quota.
2. **Retry loop** (in `GoogleMapRequest`) — up to 6 attempts; 429/5xx and network errors retry with backoff.
3. **Per attempt** — `_billing_scope()` reserves or records quota, then `_do_http()` runs once.
4. **Refund** — only if the HTTP request was **not executed** (connect/timeout errors). Responses received (any status) keep the charge.

## Quota

- `await request.check_quota()` → `QuotaBalance` with **`used`** and **`balance`** (two ints) for the request’s primary SKU.
- Tracking/enforcement flags: `GMAPS_QUOTA_TRACKING`, `GMAPS_QUOTA_ENFORCE`, `FOGG_ENV=dev` (same semantics as before).
- Raises `GmapsQuotaExceededError` when enforcement blocks an attempt.

## Environment

Variables use **module namespaces** (see comments in `.env-template`).

| Variable | Module | Default |
|----------|--------|---------|
| `GOOGLE_MAPS_API_KEY` | — | (required for live calls) |
| `GMAPS_QUOTA_*` | `quota.store` | see template |
| `GMAPS_CACHE_*` | `response_cache` | enabled, TTL 3600s |
| `GMAPS_REQUESTS_BASE_MAX_RETRIES` | `requests.base` | `5` (6 HTTP tries total) |
| `GMAPS_REQUESTS_BASE_RETRY_WAIT_INITIAL_SECONDS` | `requests.base` | `1` |
| `GMAPS_REQUESTS_BASE_RETRY_WAIT_MAX_SECONDS` | `requests.base` | `60` |

See `.env-template` for the full list.
