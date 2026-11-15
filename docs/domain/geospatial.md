# Geospatial model (PostGIS)

How FOGG stores **geometry**, runs **fast** containment and proximity queries, and ties **events** (e.g. city-wide strike) to **activities** at named POIs (e.g. World Trade Center) without a knowledge graph or full-table scans.

**Related:** [domain-model.md](domain-model.md) (Place, Event, Activity), [schema.dbml](schema.dbml), [google-maps-alignment.md](../google-maps-alignment.md).

---

## Problem

- **Events** attach to a **place** (often a city or region).
- **Activities** attach to a **place** (often a POI with no explicit “New York” in the label).
- Impact questions (“which activities are inside this strike?”) need **geo**, not string matching or loading every row into the app/LLM.

---

## Approach

**Postgres + PostGIS** on the same database as the rest of the schema.

| Store | Geometry | Typical use |
|-------|----------|-------------|
| **Place (POI)** | Point (`geom`) | Activity location |
| **Place (region)** | Polygon (`bounds_geom`) from Google **viewport** or drawn strike zone | City / area |
| **Event** | Optional **`affected_geom`** when impact area ≠ place point/bounds | Custom strike polygon |
| **Home (bio)** | Optional point on **`user_bio_details`** | Itinerary home anchor |
| **Route (overland)** | **`routes.path_geom`** linestring from Google encoded polyline | Path ∩ event area; near-route queries; NULL for air/sea |

**GiST indexes** on geometry columns so queries use the index (no “fetch all places and loop in Python”).

Enable extension in migrations:

```sql
CREATE EXTENSION IF NOT EXISTS postgis;
```

DBML uses `text` placeholders for geography types; see comments on [schema.dbml](schema.dbml) columns.

---

## Ingest (keep geom in sync)

1. **Pin / Geocode / Places `location`:** write **`places.geom`** only (e.g. `ST_SetSRID(ST_MakePoint(lng, lat), 4326)::geography` at ingest — no separate lat/lng columns).
2. **Places / Geocode with viewport:** persist `google_viewport` (JSON) and build **`bounds_geom`** as a rectangle polygon (southwest/northeast from Google bounds).
3. **City-wide event** on a locality place: use that place’s **`bounds_geom`** for containment, or copy into **`events.affected_geom`** if the event shape is edited.
4. **Custom strike:** agent/user draws polygon → **`events.affected_geom`** only ( **`place_id`** still names the anchor, e.g. “New York”).

Use **`geography`** (meters on spheroid) for distance/buffer; **`geometry`** is fine if you standardize on 4326 and accept spheroid error for short ranges.

---

## Core queries (indexed)

**Activities affected by an event polygon** (scope by user/trip first):

```sql
SELECT a.id
FROM activities a
JOIN places p ON p.id = a.place_id
WHERE a.trip_id = $1
  AND p.geom IS NOT NULL
  AND ST_Contains($2::geography, p.geom);
-- $2 = events.affected_geom OR places.bounds_geom OR ST_Buffer(place.geom, radius)
```

**Places near a point** (nearest hospital, station):

```sql
SELECT p.id, ST_Distance(p.geom, $center) AS dist_m
FROM places p
WHERE p.user_id = $1
  AND ST_DWithin(p.geom, $center, $max_m)
ORDER BY p.geom <-> $center
LIMIT $k;
```

**Event vs catalog without custom polygon:** if event **`place_id`** is NYC and **`bounds_geom`** is set, same **`ST_Contains(bounds_geom, activity.geom)`** — WTC resolves as a point inside the city polygon even when the activity label omits “New York”.

Always combine spatial filters with **btree** filters (`user_id`, `trip_id`) so GiST works on a bounded set.

---

## Product hooks

| Trigger | Action |
|---------|--------|
| Event **`affected_geom`** created/updated | SQL job: affected **activity** ids → mark **snapshots** **broken**, optional **monitor** **reminder** rows |
| **Monitor** on event | Re-run containment when geometry or event status changes |
| Agent “who’s affected?” | Tool calls indexed query; cite ids — do not scan full catalog |
| **Itinerary** updated (head snapshot) | **Proximity:** tagged interests from **`tagged_place_refs`** on trip **messages** + **preferences** → **`ST_DWithin`** / **`ST_Contains`** vs activity points and route polylines → optional **reminder** or dialogue nudge |

### Tagged place interests (messages & preferences)

Users/agents do not store coordinates in prose. Text uses inline tags, e.g. `<place id=0>New York</place>`; **`tagged_place_refs`** maps **`tag_index`** → **`place_id`** (see [domain-model.md](domain-model.md)). Spatial alerts join refs for the **user** / **trip** to **`places.geom`** or **`bounds_geom`**, then test against the materialized path (activities + decoded **`routes.google_route_ref`** polylines). Use **`proximity_radius_m`** on a ref when the interest is a POI “near the line” rather than a region polygon.

---

## What we are not doing (v1)

- Separate **knowledge graph** for “WTC ∈ NYC” when containment handles it.
- **LLM-only** “list affected activities” without a geo query.
- Loading all **places** for a user into memory for point-in-polygon in application code.

Optional later: **`place_admin_keys`** jsonb (locality/country ids from Geocode) for cheap non-PostGIS filters; PostGIS remains source of truth for distance and custom polygons.

---

## DDL sketch (migration; not exhaustive)

```sql
ALTER TABLE places
  ADD COLUMN geom geography(POINT, 4326),
  ADD COLUMN bounds_geom geography(POLYGON, 4326);

CREATE INDEX places_geom_gix ON places USING GIST (geom);
CREATE INDEX places_bounds_geom_gix ON places USING GIST (bounds_geom);

ALTER TABLE events
  ADD COLUMN affected_geom geography(POLYGON, 4326);

CREATE INDEX events_affected_geom_gix ON events USING GIST (affected_geom);
```

Maintain **`geom` / `bounds_geom`** on place insert/update (trigger or application layer after `gmaps` Geocode/Places).

```sql
ALTER TABLE routes
  ADD COLUMN path_geom geography(LINESTRING, 4326);

CREATE INDEX routes_path_geom_gix ON routes USING GIST (path_geom)
  WHERE path_geom IS NOT NULL;
```

Populate **`path_geom`** when **`computeRoutes`** returns a polyline (overland modes); leave **NULL** for air, open-ocean, or routes not yet computed.
