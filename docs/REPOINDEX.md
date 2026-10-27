# Python repository index

**Last review:** 2026-10-27 — full python-code-review pass; see [`CODEREVIEW.md`](CODEREVIEW.md) (quota/cache interaction, ruff in dev deps).

## Packages

| Path | Package | Purpose |
|------|---------|---------|
| `src/gmaps/` | `gmaps` | In-process Google Maps client: models, transport (retry + cache), quota enforcement |

Entrypoints: import from `gmaps` / `gmaps.client`; benchmarks via `python -m benchmarks`.

## Tests

| Path | Covers |
|------|--------|
| `tests/` | `gmaps` client, SKU classifier, transport, quota enforcement |

Run: `uv run pytest tests/`

## Benchmarks

| Path | Purpose |
|------|---------|
| `benchmarks/` | Mocked Google HTTP; overhead vs simulated latency (`pytest-benchmark`, `python -m benchmarks`) |

## Scripts & tools

| Path | Purpose |
|------|---------|
| `scripts/` | Google Maps API doc sync / Swagger serve |
| `tools/` | (placeholder for future dev tools) |

## Agents

`agents/` — reserved for FOGG travel-agent harness (no Python yet). See stub note in `agents/REPOINDEX.md`.

## Configuration

- `.env-template` — `GOOGLE_MAPS_API_KEY`, Redis, quota, cache
- `pyproject.toml` — hatchling wheel for `gmaps`, pytest config
