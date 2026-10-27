# FOGG — agent orientation

Read this file first for repo layout, entrypoints, and where human-facing docs live.

**Last updated:** 2026-10-27

## What this repo is

FOGG is a travel-agent project. Today the main shipped code is **`gmaps`**: an in-process async Google Maps client (request classes, local quota, Redis cache). The **`agents/`** tree is reserved for future harness code.

## Packages

| Path | Import | Purpose |
|------|--------|---------|
| `src/gmaps/` | `gmaps` | Google Maps client package |
| `src/gmaps/requests/` | `gmaps.requests` | `GoogleMapRequest[T]` subclasses — `call()`, `check_quota()` |
| `src/gmaps/quota/` | `gmaps.quota` | Usage store (Redis/SQLite), free-tier caps |

**Call pattern:** construct a request (e.g. `PlacesTextSearchRequest(...)`), then `await req.call()`. Quota: `await req.check_quota()` → `QuotaBalance(used, balance)`.

**Benchmarks:** `uv run python -m benchmarks` or `uv run pytest benchmarks/ -m benchmark`.

## Tests

| Path | Covers |
|------|--------|
| `tests/test_requests.py` | All eight request classes, cache, quota, retry, `GMAPS_REQUESTS_BASE_*` |

Run: `uv run pytest tests/`

## Configuration

- `.env-template` — env vars by module namespace (`GMAPS_QUOTA_*`, `GMAPS_CACHE_*`, `GMAPS_REQUESTS_BASE_*`)
- `pyproject.toml` — hatchling wheel (`gmaps`), pytest markers

## Human docs

| Path | Audience |
|------|----------|
| [`docs/gmaps-client.md`](docs/gmaps-client.md) | Integrators using `gmaps` |

Use **Postman** (Google Maps Platform workspace) for API exploration — not checked into this repo.

## Cursor / review

- **Collaboration:** `.cursor/rules/collaboration.mdc`
- **Commits:** `.cursor/rules/git-commits.mdc` (Conventional Commits)
- **Python review:** `.cursor/skills/python-code-review/SKILL.md` — update **this file** when layout or entrypoints change; report findings in the review reply

## Agents directory

`agents/` — future FOGG agent harness (no Python package yet).
