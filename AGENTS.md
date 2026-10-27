# FOGG — agent orientation

Read this file first for repo layout, entrypoints, and where human-facing docs live.

**Last updated:** 2026-10-27

## What this repo is

FOGG is a travel-agent project.

| Area | Path | Status |
|------|------|--------|
| **Backend** | `backend/gmaps/` | Shipped — in-process async Google Maps client |
| **Frontend** | `frontend/` | Flutter app (Android, web, iOS later); **dialogue shell + workspace frames** — see [`docs/dialogue-interface.md`](docs/dialogue-interface.md) |
| **Agents** | `agents/` | Reserved for future harness code |

## Client platform plan (Flutter)

We use **Flutter** for one Dart codebase across **Android, web, and iOS** (iOS deferred).

**Near-term (Linux dev):** run on **Chrome/web** and **Android** emulator or device. **Defer Apple** until a Mac (or CI + TestFlight) is worth it — shared UI and logic should not block this.

**Maps:** start with **OSM** (e.g. `flutter_map`); route/place **data** from our **backend** (GeoJSON / polylines), not map tiles from `gmaps`. Add **Google basemap** later with platform keys + optional App Check — separate from server-side `GOOGLE_MAPS_API_KEY`.

**Backend auth (later):** users authenticate to **our API** (e.g. JWT); Google keys stay on the server for Places/Routes/Geocode. Browser may use a **referrer-restricted** Maps key only if we embed Google map widgets.

### Gotchas (avoid hidden debt)

- Choose **plugins with iOS + Android + web support** even when only testing Android/web.
- Keep **platform-specific code thin**; don’t scatter web-only assumptions without abstractions (`shared_preferences`, responsive layout, safe areas).
- **Do not** put server `GOOGLE_MAPS_API_KEY` in the Flutter bundle for REST calls — call our backend.
- **`ios/`** exists in the Flutter tree but is **ignored operationally** until Mac/Xcode or **CI → TestFlight** (paid Apple Developer Program for TestFlight; free Personal Team only for own device + Mac + ~7-day signing).
- **GCP does not offer cloud Macs**; iOS builds need macOS runners (GitHub Actions, EAS, AWS EC2 Mac, etc.).

### Dev bootstrap (`setup.sh`)

From repo root, **one-time** (or after deleting `.tools/`):

```bash
./setup.sh
source .tools/env.sh
```

Installs **project-local** `uv`, managed **Python**, and **Flutter** under `.tools/` — does not change `~/.bashrc` or rely on system Python/uv/Flutter. Requires **git** and **curl** on the host. Re-run safely. Also installs **gitleaks** (`.tools/gitleaks/`) and runs **`pre-commit install`** so commits run Ruff + secret scanning.

**Pre-commit:** config in `.pre-commit-config.yaml`; gitleaks uses `scripts/gitleaks-staged.sh` and `.gitleaks.toml`. Manual: `uv run pre-commit run --all-files`.

### Frontend commands

After `source .tools/env.sh`, from `frontend/`:

```bash
flutter pub get
flutter run -d chrome    # web
flutter run -d android   # Android device/emulator (SDK separate)
```

**Map UI:** `frontend/lib/map/` — `FoggMap` + `MapBackend` (OSM via `flutter_map` today). Flip basemap in `lib/config/app_map_config.dart` (`MapEngine.googleMaps` when Google SDK keys exist).

## Backend packages

| Path | Import | Purpose |
|------|--------|---------|
| `backend/gmaps/` | `gmaps` | Google Maps client package |
| `backend/gmaps/requests/` | `gmaps.requests` | `GoogleMapRequest[T]` subclasses — `call()`, `check_quota()` |
| `backend/gmaps/quota/` | `gmaps.quota` | Usage store (Redis/SQLite), free-tier caps |

**Call pattern:** construct a request (e.g. `PlacesTextSearchRequest(...)`), then `await req.call()`. Quota: `await req.check_quota()` → `QuotaBalance(used, balance)`.

**Benchmarks:** `uv run python -m benchmarks` or `uv run pytest benchmarks/ -m benchmark`.

## Tests

| Path | Covers |
|------|--------|
| `tests/test_requests.py` | All eight request classes, cache, quota, retry, `GMAPS_REQUESTS_BASE_*` |

Run unit tests: `uv run pytest -m unit` (same as pre-commit). Integration: `uv run pytest -m integration`. Benchmarks: `uv run pytest benchmarks/ -m benchmark`.

## Configuration

- `.env-template` — env vars by module namespace (`GMAPS_QUOTA_*`, `GMAPS_CACHE_*`, `GMAPS_REQUESTS_BASE_*`)
- `pyproject.toml` — hatchling wheel (`gmaps`), pytest markers

## Human docs

| Path | Audience |
|------|----------|
| [`docs/gmaps-client.md`](docs/gmaps-client.md) | Integrators using `gmaps` |
| [`docs/domain-model.md`](docs/domain-model.md) | Trip / itinerary / destination / versioning domain language |

Use **Postman** (Google Maps Platform workspace) for API exploration — not checked into this repo.

## Cursor / review

- **Collaboration:** `.cursor/rules/collaboration.mdc`
- **Commits:** `.cursor/rules/git-commits.mdc` (Conventional Commits)
- **Python review:** `.cursor/skills/python-code-review/SKILL.md` — update **this file** when layout or entrypoints change; report findings in the review reply

## Agents directory

`agents/` — future FOGG agent harness (no Python package yet).
