# Docs

Documentation for FOGG.

## Product & planning

- [`domain/`](domain/) — **domain model**, **DBML** ([`schema.dbml`](domain/schema.dbml)), [**geospatial**](domain/geospatial.md) (PostGIS)
- [`user-journeys.md`](user-journeys.md) — storyboard, user journeys, phased roadmap (living substitute for a ticket board)
- [`dialogue-interface.md`](dialogue-interface.md) — dialogue-first UI: panels, frames, agent protocol, architecture implications
- [`frame-journey-map.md`](frame-journey-map.md) — which frames serve which journey steps; gaps and redundancies
- [`latency-optimization.md`](latency-optimization.md) — perceived latency, baselines, system-level perf tests
- [`ideas.md`](ideas.md) — exploratory ideas and constraints not yet committed to the product roadmap

## Integrators

- [`agent-api.md`](agent-api.md) — travel agent FastAPI **v1** (`/v1/users/{user_id}/chat`, SSE stream, layout routes)
- [`gmaps-client.md`](gmaps-client.md) — in-process `gmaps` request classes, env vars, quota behavior
- [`google-maps-pricing.md`](google-maps-pricing.md) — pricing matrix for Google Maps endpoints used by FOGG
- [`google-maps-quota-safety.md`](google-maps-quota-safety.md) — quota enforcement limits, Google-side hard stops, and next-day billing reconciliation
- [`google-maps-alignment.md`](google-maps-alignment.md) — FOGG domain ↔ Google Places / Routes / Geocoding

Repo landscape for coding agents: **[`AGENTS.md`](../AGENTS.md)** at the repository root.
