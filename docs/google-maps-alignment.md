# FOGG domain ↔ Google Maps Platform

Alignment reference so we don’t mentally merge **trip planning concepts** (FOGG) with **Google API objects** (Places, Routes, Geocoding). Our in-process client is [`gmaps`](../backend/gmaps/) — see [`gmaps-client.md`](gmaps-client.md).

**Rule:** FOGG owns **Trip**, **Itinerary**, **draft/version/fork**. Google owns **Place**, **Waypoint**, **Route/Leg**. Persist **both ids** where linked (`fogg_destination_id` + optional `google_place_id`).

---

## What Google does *not* have

| FOGG concept | Notes |
|--------------|--------|
| **Trip** | Product container; only in FOGG. |
| **Itinerary** | Time + destination spans; only in FOGG. |
| **Destination span** | Date range on a destination; only in FOGG. |
| **Draft / version / fork** | Change model; only in FOGG. |
| **Booking** (FOGG record) | We track external confirmations; not a Google Maps core object. |
| **Place profile** (FOGG) | Our subtype + planning fields; *partially* filled from Place details. |

Google answers: “what is this place?”, “how do I drive there?”, “what’s at this lat/lng?” — not “what is Alex’s vacation plan v3?”.

---

## Google APIs we use (via `gmaps`)

| API | `gmaps` request | Primary Google nouns |
|-----|-----------------|----------------------|
| Places (New) | `PlacesTextSearchRequest`, `PlacesSearchNearbyRequest`, `PlacesAutocompleteRequest`, `PlacesGetRequest` | **Place**, `placeId`, `types[]`, `primaryType` |
| Routes v2 | `RoutesComputeRoutesRequest`, `RoutesComputeRouteMatrixRequest` | **Waypoint**, **Route**, **RouteLeg**, **RouteLegStep**, **Polyline** |
| Geocoding (legacy) | `GeocodeRequest` | **GeocodeResult**, `address_components[]`, `geometry` |
| Directions (legacy) | `DirectionsRequest` | **route**, **leg**, **step** (older shape; prefer Routes for new code) |

Display maps (OSM / Maps JS) are separate from these data APIs — see [dialogue-interface.md](dialogue-interface.md).

---

## Destination kinds ↔ Google

FOGG **destination kinds** are planning hierarchy. Google does not expose one enum for “country vs city”; infer from **Place types** and/or **Geocoding address components**.

| FOGG destination kind | Typical Google source | Hints |
|-------------------------|----------------------|--------|
| **country** | Geocode / Place | `types`: `country`, `political`; component `country` |
| **region** | Geocode / Place | `administrative_area_level_1`, `administrative_area_level_2`, … |
| **city** | Geocode / Place | `locality`, `postal_town`, `administrative_area_level_3` |
| **district** | Geocode / Place | `sublocality`, `neighborhood`, `postal_code` (context-dependent) |
| **venue** | **Places API** | Place resource with `id`, `displayName`, `primaryType`; search/get/autocomplete |
| **point** | **LatLng** only | `Waypoint.location`, Geocode reverse lat/lng, map pin — **no** `placeId` required |

**Persistence on FOGG destination (recommended):**

```text
google_place_id     # when venue (or geocoded entity with stable id)
google_lat_lng        # always for point; optional anchor for others
google_viewport       # from Place.viewport or Geocode bounds — map framing
google_types[]        # snapshot for debugging / re-classification (not source of truth)
```

**Do not** store Google’s `types[]` as FOGG **kind** without normalization — Google returns many tags; FOGG picks one **kind** for the itinerary tree.

Docs: [Place resource](https://developers.google.com/maps/documentation/places/web-service/reference/rest/v1/places), [Place types](https://developers.google.com/maps/documentation/places/web-service/place-types), [Geocoding address types](https://developers.google.com/maps/documentation/geocoding/requests-geocoding#Types).

---

## Place profile ↔ Google Place fields

FOGG **place profile** = optional enrichment on a **destination** (usually **venue**). Map from **`PlacesGetRequest`** field mask (billable — request only what you need):

| FOGG place profile | Google Place field (New) |
|--------------------|---------------------------|
| Coordinates | `location` (LatLng) |
| Bounds / map focus | `viewport` |
| Address | `formattedAddress`, `addressComponents[]`, `postalAddress` |
| Contact | `nationalPhoneNumber`, `internationalPhoneNumber`, `websiteUri` |
| Reviews | `rating`, `userRatingCount`, reviews if requested in mask |
| Operating hours | `regularOpeningHours`, `currentOpeningHours`, `utcOffsetMinutes` |
| Pricing (weak) | No single “price level” on all SKUs — may use `priceLevel` where available; FOGG **pricing** is often our estimate or booking record |
| Display name | `displayName` |
| Profile **subtype** (FOGG) | Approximate map from `primaryType` / `types[]` — see table below |

FOGG **profile subtype** is a **small planning enum**. Google **`primaryType`** is a large taxonomy — many-to-one mapping:

| FOGG profile subtype | Example Google `primaryType` / `types` |
|----------------------|----------------------------------------|
| accommodation | `lodging`, `hotel`, `hostel`, … |
| food | `restaurant`, `cafe`, `bar`, … |
| attraction | `tourist_attraction`, `museum`, `park`, … |
| utility | `atm`, `laundry`, … |
| security | `police`, … |
| embassy | `embassy`, … |
| medical | `hospital`, `pharmacy`, `doctor`, … |
| transport (location) | `airport`, `train_station`, `transit_station`, `bus_station`, … |

Unmapped Google types → store on destination as `google_primary_type` and let the agent pick a FOGG subtype in dialogue.

---

## Journey & transport ↔ Routes API

| FOGG | Google Routes v2 |
|------|------------------|
| **Journey** (A → B, times, mode) | One **`computeRoutes`** request: `origin` + `destination` Waypoints → **`Route`** (often **one `RouteLeg`** if no stopover intermediates) |
| Journey with stopover | `intermediates[]` without `via: true` → **multiple `RouteLeg`s** — FOGG may model as **one journey** with legs or **multiple journeys**; pick one convention and stick to it (recommend: **one FOGG journey = one RouteLeg** when stopovers divide legs) |
| Pass-through shaping | `intermediates` with **`via: true`** → no extra leg; path only |
| **Transport.mode** | `travelMode`: `DRIVE`, `WALK`, `BICYCLE`, `TRANSIT`, `TWO_WHEELER`, … |
| Departure / arrival timing | `RouteLeg.duration`, `staticDuration`; optional `departureTime` / traffic on request |
| Path geometry | `RouteLeg.polyline` (encoded) → map frame overlay |
| Operator (airline, etc.) | **Not** in core Routes response for all modes — FOGG **transport.operator** from booking / user / future APIs |
| **Booking** / documents | **Not Google** — FOGG records after external purchase |

**Waypoint ↔ FOGG destination:**

| Waypoint field | Use when FOGG destination is |
|----------------|------------------------------|
| `placeId` | **venue** (has `google_place_id`) |
| `address` | Geocoded string / formatted address |
| `location` | **point** kind or snapped road point |

Docs: [Waypoint](https://developers.google.com/maps/documentation/routes/reference/rest/v2/Waypoint), [Understand route response](https://developers.google.com/maps/documentation/routes/understand-route-response), [computeRoutes](https://developers.google.com/maps/documentation/routes/reference/rest/v2/TopLevel/computeRoutes).

**Route matrix:** `RoutesComputeRouteMatrixRequest` — many-to-many durations/distances; useful for “which hotel is least travel time?” not a full **Journey** until you pick one pair and `computeRoutes`.

---

## Planning flow ↔ API calls (typical)

| User / agent action | FOGG | Google (via `gmaps`) |
|---------------------|------|----------------------|
| “Australia 1–5 Dec” | Create **destination** kind **country** + span | Optional: Geocode "Australia" → bounds/viewport |
| “Find coffee in Kyoto” | Draft destinations **venue** | `PlacesTextSearchRequest` → Place candidates |
| “Details for this hotel” | Attach **place profile** | `PlacesGetRequest`(place id) |
| “How do I get from hotel to museum?” | Create **journey** + transport mode | `RoutesComputeRoutesRequest`(origin/dest Waypoints) |
| Drop pin on map | **destination** kind **point** | Reverse Geocode optional if naming needed |
| Compare 3 areas to stay | Itinerary options in **draft** | Matrix or multiple route computes |

---

## Geocoding vs Places

| Need | Prefer |
|------|--------|
| Named POI, hours, reviews | **Places** (search / get) |
| “Sydney, Australia” hierarchy, bounds | **Geocoding** forward |
| Lat/lng → label | **Geocoding** reverse |
| Autocomplete in UI | **Places Autocomplete** (widget or API) |

A **venue** destination should usually get a **`google_place_id`** from Places. A **country/city** span may use Geocode once and store **viewport/bounds**. A **point** destination stores **lat/lng**; Geocode only if the user wants a label.

---

## Legacy vs New

| Prefer | Legacy | Notes |
|--------|--------|--------|
| Routing | **Routes v2** (`RoutesComputeRoutesRequest`) | `DirectionsRequest` still in `gmaps` for parity |
| Places | **Places API (New)** | Field masks control cost; see SKU mapping in code |
| Geocoding | Geocoding API | Still valid for hierarchy / reverse |

---

## Anti-patterns

- Treating a Google **`Route`** as FOGG **itinerary** — route is one movement; itinerary is the whole trip plan.
- Storing only formatted address — always store **`place_id`** when Places gives one.
- Using **`types[]`** as FOGG **destination kind** without a normalization layer.
- Confusing **`RouteLegStep`** (turn-by-turn) with FOGG **destination span** — steps are navigation instructions inside one **journey** leg.

---

## Related

- [Domain model](domain-model.md) — FOGG terms (destination kinds, place profile, journey)
- [gmaps client](gmaps-client.md) — request classes and env
- [Frame ↔ journey map](frame-journey-map.md) — UI frames (map shows polylines from Route legs)

When backend entities exist, add a table of stored field names mirroring this doc in code or OpenAPI — not duplicated here.
