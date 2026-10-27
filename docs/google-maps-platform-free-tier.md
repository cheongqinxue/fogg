# Google Maps Platform — research for FOGG

Research date: **2026-10-24**. Official pricing and caps change; verify against the links in [Sources](#sources) before budgeting production usage.

## How this relates to FOGG

From the [project README](../README.md), FOGG is a **personalized travel “butler”**: discover options that fit budget and taste, surface backup plans when things go wrong, and learn from whether the user follows suggestions. For a first version (“smart suggestion machine”), Google Maps Platform can supply:

| FOGG need | Google capability |
|-----------|-------------------|
| Find places (hotels, food, sights) | Places API (New): Text Search, Nearby Search, Autocomplete |
| Quality signals (rating, hours, price level) | Place Details field masks (tiered billing) |
| Written reviews | Place Details `reviews` (limited; see below) |
| Plan a route / day path | Routes API `computeRoutes`, optional Route Optimization |
| Reroute when plans change | Same APIs — **each new route request is a billable event** |
| Show results on a map | Maps JavaScript API (Dynamic Maps), Embed, Static Maps, or Map Tiles API |
| Weather / context (optional) | Environment Weather API or Maps Grounding Lite `lookup_weather` |
| Agent-friendly integration | **Maps Grounding Lite** (MCP server: places, routes summary, weather) |

Billing must be enabled on a Google Cloud project even when usage stays within free caps. New accounts may also receive a **$300 Maps trial credit** (separate from per-SKU free usage).

---

## Free-tier model (since 2025-03-01)

Google **replaced the single pooled $200/month credit** with **per-SKU free usage caps** that reset on the **1st of each month (midnight Pacific Time)**.

| Category | Typical free billable events / month / SKU |
|----------|---------------------------------------------|
| **Essentials** | 10,000 (most SKUs) |
| **Pro** | 5,000 |
| **Enterprise** | 1,000 |
| **Exceptions (unlimited free)** | e.g. Maps **Embed**, **Maps SDK** (mobile), some **Place Details / Text Search “IDs Only”** SKUs, Autocomplete **session** linkage |
| **Map Tiles (2D & Street View)** | **100,000** free billable events per tile SKU (Essentials) |

You are billed at the **highest SKU tier** touched by a single request (field mask for Places; feature flags for Routes).

---

## APIs and endpoints (by job)

### 1. Discover places

**Places API (New)** — REST base: `https://places.googleapis.com/v1/places`

| Method | Purpose | Typical free cap (SKU) |
|--------|---------|-------------------------|
| `places:searchText` | Query by text (“ramen near Shibuya”) | Text Search **Pro** — **5,000**/mo (Essentials **IDs Only** — unlimited) |
| `places:searchNearby` | Query by location + radius/type | Nearby Search **Pro** — **5,000**/mo |
| `places:autocomplete` | Typeahead (UI or agent disambiguation) | Autocomplete Requests — **10,000**/mo; **sessions** tied to Place Details can be cheaper |
| `places/{placeId}` | Full detail for one place | Depends on **field mask** (see below) |

**Legacy** Places (Nearby/Text Search/Details) still works but is **Legacy status** — prefer Places API (New) for new work.

**Cost tip:** Use **IDs-only** search responses, then call Place Details only for a shortlist. Cache `place_id` + your agent’s notes server-side (respect [Google Maps Platform Terms](https://cloud.google.com/maps-platform/terms) — place data is not indefinitely storable for all fields).

### 2. Reviews and reputation

| Data | API | SKU when requested | Free cap |
|------|-----|-------------------|----------|
| `rating`, `userRatingCount`, `regularOpeningHours`, `websiteUri`, … | Place Details (New) | **Enterprise** | **1,000**/mo |
| `reviews[]` (max **5** reviews, relevance-sorted) | Place Details (New) | **Enterprise + Atmosphere** | **1,000**/mo |
| `reviewSummary` (AI summary of reviews) | Place Details (New) | **Enterprise + Atmosphere** | **1,000**/mo |
| `editorialSummary`, `generativeSummary`, amenity booleans (`servesVegetarianFood`, …) | Place Details (New) | **Enterprise + Atmosphere** | **1,000**/mo |

Important limitations for FOGG:

- **No pagination for consumer reviews** in Places API — at most **five** `Review` objects per place. For deep review mining, Google expects users to follow `googleMapsLinks.reviewsUri` or you use **Google Business Profile API** (only for locations **you manage**, not arbitrary POIs).
- **`reviewSummary`** may fit an agent better than raw reviews: one call, less token noise, still **Enterprise + Atmosphere** pricing.
- Requesting **`reviews` forces the highest tier** for that Details call even if you only wanted address (Essentials).

Legacy equivalent: **Atmosphere Data** add-on (Enterprise, **1,000**/mo) on top of Details/Search.

### 3. Routes, distance, rerouting

**Routes API (preferred)** — `POST https://routes.googleapis.com/directions/v2:computeRoutes`

| Method | Purpose | Billing unit | Essentials free cap |
|--------|---------|--------------|---------------------|
| `computeRoutes` | A→B (optional waypoints, polyline, steps) | **Per request** | **10,000**/mo |
| `computeRouteMatrix` | Many origins × destinations (compare options) | **Per element** (origins × destinations) | **10,000 elements**/mo |

**SKU tier (Routes)** — billed by **features used**, not only endpoint:

| Tier | Triggers (examples) | Free cap |
|------|---------------------|----------|
| **Essentials** | Basic routing, ≤ **10** intermediate waypoints | **10,000**/mo |
| **Pro** | `TRAFFIC_AWARE`, `TRAFFIC_AWARE_OPTIMAL`, >10 waypoints, waypoint **optimization**, etc. | **5,000**/mo |
| **Enterprise** | Two-wheel routing, large vehicles, etc. | **1,000**/mo |

**Legacy (still available):** Directions API (**10,000**/mo Essentials), Distance Matrix (**10,000** elements/mo). Google labels these Legacy; new features land on Routes API.

**Rerouting:** Treat every “plan B” polyline as another `computeRoutes` (or matrix cell). For an agent that replans often, **Essentials without live traffic** preserves the **10k** bucket; enable traffic only when the user is actively navigating.

**Multi-stop trip ordering:** Route Optimization API — Single Vehicle Routing (**5,000**/mo Pro). Useful for “best order for these five stops today.”

**Not for turn-by-turn in FOGG v1:** Navigation SDK is mobile-centric and separate from web agent flows.

### 4. Display on a map

| Product | Best for | Free tier highlight |
|---------|----------|---------------------|
| **Maps JavaScript API** | Interactive web UI, markers, polylines from Routes | **Dynamic Maps** — **10,000 loads**/mo |
| **Maps Embed API** | Simple iframe embed of a place or directions | **Unlimited** |
| **Static Maps API** | Thumbnail map + `path` for route polyline | **10,000**/mo |
| **Map Tiles API** | Custom renderers (2D tiles) | **100,000** tile requests/mo (Essentials 2D) |
| **Mobile Maps SDK** | Native apps | **Unlimited** map loads (SDK SKU) |

Drawing a route: get `routes.polyline.encodedPolyline` from Routes API, decode, overlay on Dynamic Maps or Static Maps — **map load** and **route compute** are separate SKUs.

### 5. Geocoding, time zones, address cleanup

| API | Use in FOGG | Essentials free cap |
|-----|-------------|---------------------|
| **Geocoding API** | “Hotel name → lat/lng” | **10,000**/mo |
| **Time Zone API** | “Landing at 11pm — what local time?” | **10,000**/mo |
| **Address Validation** | Strict mailing addresses (less common for leisure travel) | Pro **5,000**/mo |

Places Details already returns `location` and addresses for known `place_id`s — avoid double-paying Geocoding when IDs come from Search.

### 6. Environment (optional for travel agent)

| API | Free cap (Essentials) | Notes |
|-----|----------------------|--------|
| **Weather API** | **10,000**/mo | Forecasts alongside itinerary |
| **Air Quality API** | **10,000**/mo | Sensitive travelers, outdoor plans |
| **Pollen API** | **5,000**/mo (Pro) | Seasonal |

### 7. Maps Grounding Lite (agent / MCP)

Hosted MCP: `https://mapstools.googleapis.com/mcp`

| Tool | What it gives FOGG | What it does **not** give |
|------|--------------------|---------------------------|
| `search_places` | AI place summaries + Place IDs + Maps links | Full structured Details; unlimited reviews |
| `compute_routes` | Distance/duration (driving/walking) | Step-by-step directions, live traffic, navigation |
| `lookup_weather` | Current + hourly + daily | — |
| `resolve_names` / `resolve_maps_urls` | Text/URL → Place ID | Billed as Text Search Essentials (IDs Only) — **no charge** per Google |

SKU **Maps Grounding Lite**: **10,000** free billable events/mo (Essentials). Strong fit for a **prototype agent**; pair with Places/Routes REST when you need polylines, exact hours, or review text.

Attribution: Grounded outputs must show **Google Maps sources** next to generated text ([Grounding Lite policies](https://developers.google.com/maps/ai/grounding-lite)).

---

## What fits comfortably in the free tier?

Rough **personal / low-traffic agent** budget (one Google Cloud billing account, hobby scale):

| Workflow | Approx. monthly calls | Fits free tier? |
|----------|----------------------|-----------------|
| User asks 200 trip questions; Grounding Lite `search_places` each time | ~200 | Yes (10k) |
| Shortlist 30 places with `reviewSummary` + rating (Enterprise+Atmosphere Details) | ~30 | Yes (1k) |
| Build 50 alternative driving legs (Essentials, no traffic) | ~50 | Yes (10k) |
| Compare 10 hotels × 5 candidate restaurants (matrix 10×5 = 50 elements) | 50 elements | Yes (10k) |
| Web UI with 500 Dynamic Map loads | 500 | Yes (10k) |
| **Heavy** usage: 2k detailed review fetches/mo | 2k | **No** — Enterprise+Atmosphere caps at **1k** |

Design pattern for FOGG within free caps:

1. **Discover** with Text/Nearby Search (Pro) or Grounding Lite search.
2. **Filter** using Pro fields (`displayName`, `businessStatus`, `primaryType`) before Details.
3. **Deep dive** only on finalists with a tight field mask (`rating`, `regularOpeningHours`, `reviewSummary` — accept **Enterprise + Atmosphere** tier).
4. **Route** with Routes **Essentials** (no traffic) for planning; optionally one Pro traffic-aware call when the user commits.
5. **Map** with Embed (free) for share links, or Static Maps for thumbnails in chat.
6. **Cache** place IDs and your own derived preferences locally; refresh Details sparingly.

---

## SKU reference table (FOGG-relevant)

Free usage cap = billable events per month per SKU (global list; India has alternate numbers).

| SKU | Free cap |
|-----|----------|
| Places: Text Search Pro | 5,000 |
| Places: Nearby Search Pro | 5,000 |
| Places: Place Details Essentials | 10,000 |
| Places: Place Details Enterprise | 1,000 |
| Places: Place Details Enterprise + Atmosphere | 1,000 |
| Places: Text Search Essentials (IDs Only) | Unlimited |
| Places: Autocomplete Requests | 10,000 |
| Routes: Compute Routes Essentials | 10,000 |
| Routes: Compute Routes Pro | 5,000 |
| Routes: Compute Route Matrix Essentials | 10,000 (elements) |
| Legacy: Directions | 10,000 |
| Maps: Dynamic Maps | 10,000 |
| Maps: Static Maps | 10,000 |
| Maps: Embed | Unlimited |
| Map Tiles: 2D Map Tiles | 100,000 |
| Geocoding | 10,000 |
| Time Zone | 10,000 |
| Weather | 10,000 |
| Maps Grounding Lite | 10,000 |
| Route Optimization (single vehicle) | 5,000 |

Full list: [Google Maps Platform core services pricing](https://developers.google.com/maps/billing-and-pricing/pricing).

---

## Gaps and non-goals (within Google Maps alone)

- **Full review corpus** for arbitrary businesses — not available via Places API (5-review cap).
- **Live rebooking / real-time disruption** — needs your own logic plus optional Pro/Enterprise traffic routing; Maps does not book hotels or flights.
- **Offline maps** — limited; not aimed at agent backends.
- **Storing Google place content long-term** — restricted by license; plan for refresh + user-specific memory that is yours (preferences), not bulk cached Maps fields.

---

## Suggested stack for FOGG v1 ( opinion )

| Layer | Choice |
|-------|--------|
| Agent tools (fast prototype) | Maps Grounding Lite MCP + your LLM |
| Structured tools (precise polylines / hours) | Places API (New) + Routes API REST from Python |
| UI map | Maps Embed or Static Maps + encoded polylines |
| Secrets | `GOOGLE_MAPS_API_KEY` in `.env` (see repo security rules) |

Enable only the APIs you use; restrict the API key by API and (for web) HTTP referrer.

---

## Sources

- [Billing FAQ — monthly credit → per-SKU free usage (2025-03-01)](https://developers.google.com/maps/billing-and-pricing/faq)
- [Pay-as-you-go / free usage caps](https://developers.google.com/maps/billing-and-pricing/pay-as-you-go)
- [Core services pricing list](https://developers.google.com/maps/billing-and-pricing/pricing)
- [Places API (New) usage and billing](https://developers.google.com/maps/documentation/places/web-service/usage-and-billing)
- [Place data fields (SKU per field)](https://developers.google.com/maps/documentation/places/web-service/data-fields)
- [Place resource — `reviews` max 5](https://developers.google.com/maps/documentation/places/web-service/reference/rest/v1/places)
- [Routes API usage and billing](https://developers.google.com/maps/documentation/routes/usage-and-billing)
- [Compute Routes](https://developers.google.com/maps/documentation/routes/compute_route_directions)
- [Maps Grounding Lite](https://developers.google.com/maps/ai/grounding-lite)
- [Maps Platform pricing overview](https://mapsplatform.google.com/pricing/)
