# FOGG domain ↔ Google Maps Platform

Alignment reference so we don’t mentally merge **trip planning concepts** (FOGG) with **Google API objects** (Places, Routes, Geocoding). Our in-process client is [`gmaps`](../agent/src/gmaps/) — see [`gmaps-client.md`](gmaps-client.md).

**Rule:** FOGG owns **Trip**, **Itinerary snapshots**, **Activity**, **FOGG place**, **FOGG route**. Google owns the **Place API resource**, **Waypoint**, **Route** / **RouteLeg** (Routes API). Persist **`fogg_place_id`**, **`fogg_route_id`**, and Google ids when linked.

---

## What Google does *not* have

| FOGG concept | Notes |
|--------------|--------|
| **Trip** | Product container; only in FOGG. |
| **Itinerary** | List of **activities** (+ **routes**); only in FOGG. |
| **Route** (FOGG) | Planned move place → place (+ transport); only in FOGG. |
| **Activity** | Something we do; primarily **place** + **time**; only in FOGG. |
| **Place** (FOGG) | Persistent known location; **classification = Google types**; referenced by trip activities/routes. |
| **Itinerary snapshots** | Materialized paths + invalidation; only in FOGG. |
| **Reservation** (FOGG) | Holds, operator, payment tracking; not a Google Maps core object. |
| **Event** (FOGG) | Known happening at a **place** + duration; user catalog—not trip-scoped; not a Google Place type. |

Google answers: “what is this place?”, “how do I drive there?”, “what’s at this lat/lng?” — not “what is Alex’s vacation plan v3?”.

---

## Google APIs we use (via `gmaps`)

| API | `gmaps` request | Primary Google nouns |
|-----|-----------------|----------------------|
| Places (New) | `PlacesTextSearchRequest`, `PlacesSearchNearbyRequest`, `PlacesAutocompleteRequest`, `PlacesGetRequest` | **Place**, `placeId`, `types[]`, `primaryType` |
| Routes v2 | `RoutesComputeRoutesRequest`, `RoutesComputeRouteMatrixRequest` | **Waypoint**, **Route**, **RouteLeg**, **RouteLegStep**, **Polyline** |

Display maps (OSM / Maps JS) are separate from these data APIs — see [dialogue-interface.md](dialogue-interface.md).

---

## FOGG place ↔ Google classification

FOGG **place** classification aligns primarily with **Google Places**.

| Classification source | Fields to persist |
|-------------------------|-------------------|
| **Places API (New)** | `primaryType`, `types[]`, `id` → `google_place_id` |
| **Map pin** | Google Places `location` (LatLng) at ingest → FOGG **`geom`** |

**Persistence on FOGG place (recommended):**

```text
fogg_place_id           # FOGG entity id (activities/routes reference this)
google_place_id         # when Places/Geocode provides stable Place id
google_primary_type     # from Place.primaryType when available
google_types[]          # full type list snapshot (Places or Geocode)
geom                    # PostGIS point — canonical; from Geocode/Places location at ingest
google_viewport         # Place.viewport or Geocode bounds — map framing → bounds_geom
display_name            # Place.displayName or formatted label
address_components[]    # optional snapshot from Geocode for hierarchy display
# Context on a place → link conversation message to place (not preferences unless promoted)
```

Use **`primaryType`** and **`types[]`** in UI filters and agent reasoning (e.g. “find `restaurant` near this `locality`”).

Docs: [Place resource](https://developers.google.com/maps/documentation/places/web-service/reference/rest/v1/places), [Place types](https://developers.google.com/maps/documentation/places/web-service/place-types), [Geocoding address types](https://developers.google.com/maps/documentation/geocoding/requests-geocoding#Types).

---

## Place details ↔ Google Place fields

Hydrate FOGG **place details** from **`PlacesGetRequest`** (field mask controls cost):

| FOGG place detail | Google Place field (New) |
|-------------------|---------------------------|
| Point | `location` (LatLng) → persist as **`geom`** only |
| Bounds / map focus | `viewport` |
| Address | `formattedAddress`, `addressComponents[]`, `postalAddress` |
| Contact | `nationalPhoneNumber`, `internationalPhoneNumber`, `websiteUri` |
| Reviews | `rating`, `userRatingCount`, reviews if requested in mask |
| Operating hours | `regularOpeningHours`, `currentOpeningHours`, `utcOffsetMinutes` |
| Pricing (weak) | `priceLevel` where available; trip budget often separate FOGG fields |
| Display name | `displayName` |
| Category | **`primaryType`**, **`types[]`** (Google domain model) |

---

## FOGG route & transport ↔ Routes API

| FOGG | Google Routes v2 |
|------|------------------|
| **Route** (A → B, times, mode) | One **`computeRoutes`** request: `origin` + `destination` Waypoints → **`Route`** (often **one `RouteLeg`** if no stopover intermediates) |
| Route with stopover | `intermediates[]` without `via: true` → **multiple `RouteLeg`s** — model as **one FOGG route** with legs or **multiple FOGG routes**; recommend **one FOGG route = one `RouteLeg`** when stopovers divide legs |
| Pass-through shaping | `intermediates` with **`via: true`** → no extra leg; path only |
| **Transport.mode** | `travelMode`: `DRIVE`, `WALK`, `BICYCLE`, `TRANSIT`, `TWO_WHEELER`, … |
| Departure / arrival timing | `RouteLeg.duration`, `staticDuration`; optional `departureTime` / traffic on request |
| Path geometry | `RouteLeg.polyline` (encoded) → map frame overlay |
| Operator (airline, etc.) | **Not** in core Routes response for all modes — FOGG **transport.operator** from booking / user / future APIs |
| **Booking** / documents | **Not Google** — FOGG records after external purchase |

**Waypoint ↔ FOGG place:**

| Waypoint field | Use when FOGG place has |
|----------------|-------------------------|
| `placeId` | `google_place_id` |
| `address` | Geocoded / formatted address, no id |
| `location` | Build Waypoint from **`places.geom`** (derive LatLng at API boundary) |

Docs: [Waypoint](https://developers.google.com/maps/documentation/routes/reference/rest/v2/Waypoint), [Understand route response](https://developers.google.com/maps/documentation/routes/understand-route-response), [computeRoutes](https://developers.google.com/maps/documentation/routes/reference/rest/v2/TopLevel/computeRoutes).

**Route matrix:** `RoutesComputeRouteMatrixRequest` — many-to-many durations/distances; useful for “which hotel is least travel time?” not a full **FOGG route** until you pick one pair and `computeRoutes`.

---

## Planning flow ↔ API calls (typical)

| User / agent action | FOGG | Google (via `gmaps`) |
|---------------------|------|----------------------|
| “Australia 1–5 Dec” | Create **activity** + **place** (Geocode types e.g. `country`) | Geocode "Australia" → bounds/viewport, types |
| “Find coffee in Kyoto” | Draft **places** from search | `PlacesTextSearchRequest` → candidates (`primaryType`, `types[]`) |
| “Details for this hotel” | Hydrate **place details** | `PlacesGetRequest`(place id) |
| “How do I get from hotel to museum?” | Create **route** + transport mode | `RoutesComputeRoutesRequest`(origin/dest Waypoints) |
| Drop pin on map | **Place** with **`geom`** only | Reverse Geocode optional for label/types |
| Compare 3 areas to stay | Itinerary options in **draft** | Matrix or multiple route computes |

---

Prefer **`google_place_id`** from Places whenever available. Country/region scope belongs on **trip** framing or **places** in catalog—not untimed “activities.” **Activity** rows need a concrete **place** + **starts_at** (see [domain-model.md](domain/domain-model.md)). Persist **`geom`** / **`home_geom`** only (no duplicate lat/lng columns); viewport → **`bounds_geom`** ([geospatial.md](domain/geospatial.md)). Derive LatLng for Google API calls at the boundary.

---

## Anti-patterns

- Treating a Google **`Route`** as FOGG **itinerary** — route is one movement; itinerary is the whole trip plan.
- Storing only formatted address — always store **`place_id`** when Places gives one.
- Maintaining a **FOGG-only type enum** instead of Google **`primaryType` / `types[]`**.
- Confusing **`RouteLegStep`** (turn-by-turn) with FOGG **activity** — steps are navigation instructions inside one Google **RouteLeg** (linked from a FOGG **route**).

---

## Related

- [Domain model](domain/domain-model.md) — FOGG terms (place, activity, route)
- [gmaps client](gmaps-client.md) — request classes and env
- [Frame ↔ journey map](frame-journey-map.md) — UI frames (map shows polylines from Route legs)

When backend entities exist, add a table of stored field names mirroring this doc in code or OpenAPI — not duplicated here.
