# FOGG — agent orientation

Read this file first for repo layout, entrypoints, and where human-facing docs live.

**Last updated:** 2026-11-17

**Last Python review:** 2026-11-09 — agent `master_agt/` harness, thread routes, chat/SSE, Postgres checkpoints. Browser worker changes on 2026-11-17 are covered by focused offline tests; this is not a repo-wide review.

## What this repo is

FOGG is a travel-agent project.

| Area | Path | Status |
|------|------|--------|
| **Functionality modules** | `agent/src/gmaps/`, `agent/src/layout/` | Google Maps client and layout functionality used by the agent |
| **Backend API stub** | `backend/server.py` | Minimal FastAPI health/readiness service for Docker Compose; not the production API |
| **Frontend** | `frontend/svelte/` | SvelteKit browser app for phone and desktop web; chat/SSE, local layout sync, and OSM map — see [`frontend/svelte/README.md`](frontend/svelte/README.md) |
| **Agent** | `agent/` | LangGraph ReAct harness — see [`agent/README.md`](agent/README.md) |

## Client platform plan (browser first)

The product UI targets **mobile and desktop browsers**. Users may open it in Safari, Chrome, or an equivalent browser; native app packaging is not currently required.

**Frontend:** SvelteKit in `frontend/svelte/`, built as a static client-rendered SPA with SSR disabled; the agent API remains a separate service.

**Maps:** use OSM tiles and browser map layers. Route/place **data** comes from our **backend** (GeoJSON / polylines), not map tiles from `gmaps`. A Google basemap can be added later with browser-restricted keys; these are separate from server-side `GOOGLE_MAPS_API_KEY`.

**Backend auth (later):** users authenticate to **our API** (e.g. JWT); Google keys stay on the server for Places/Routes/Geocode. Browser may use a **referrer-restricted** Maps key only if we embed Google map widgets.

### Gotchas (avoid hidden debt)

- Keep browser UI interactions local and avoid repainting the map while the user types.
- **Do not** put server `GOOGLE_MAPS_API_KEY` in browser code for REST calls — call our backend.
- Native app packaging is a separate future decision; do not constrain the browser implementation around speculative cross-platform UI reuse.

### Dev bootstrap (`setup.sh`)

From repo root, **one-time** (or after deleting `.tools/`):

```bash
./setup.sh
source .tools/env.sh
```

Installs **project-local** `uv` and managed **Python** under `.tools/` — does not change `~/.bashrc` or rely on system Python/uv. Requires **git** and **curl** on the host. Re-run safely. Also installs **gitleaks** (`.tools/gitleaks/`) and runs **`pre-commit install`** so commits run Ruff + secret scanning. The Svelte frontend separately requires Node.js 20+ and npm.

**Pre-commit:** config in `.pre-commit-config.yaml`; gitleaks uses `scripts/gitleaks-staged.sh` and `.gitleaks.toml`. Manual: `uv run pre-commit run --all-files`.

### Frontend commands

Browser app, from repo root:

```bash
cd frontend/svelte
npm install
npm run dev
npm run check
npm run build
```

The Svelte app requires Node.js 20+ and npm.

The app reads `AGENT_API_BASE_URL`, `AGENT_USER_ID`, and frontend port values from the root `.env`; see [`frontend/svelte/README.md`](frontend/svelte/README.md). Svelte source is under `frontend/svelte/src/`: `lib/agent.ts` (chat/SSE and API), `lib/layout.ts` (local document and hash), `components/ChatPanel.svelte`, and `components/MapView.svelte`.

## Backend packages

| Path | Import | Purpose |
|------|--------|---------|
| `agent/src/gmaps/` | `gmaps` | Google Maps client functionality module |
| `agent/src/gmaps/requests/` | `gmaps.requests` | `GoogleMapRequest[T]` subclasses — `call()`, `check_quota()` |
| `agent/src/gmaps/quota/` | `gmaps.quota` | Usage store (Redis/SQLite), free-tier caps |
| `backend/server.py` | ASGI `app` | Compose health/readiness stub only; replace when implementing the real backend API |

**Call pattern:** construct a request (e.g. `PlacesTextSearchRequest(...)`), then `await req.call()`. Quota: `await req.check_quota()` → `QuotaBalance(used, balance)`.

**Benchmarks:** `uv run python -m benchmarks` or `uv run pytest benchmarks/ -m benchmark`.

## Tests

| Path | Covers |
|------|--------|
| `agent/tests/test_requests.py` | Google Maps requests, cache, quota, retry, request settings |
| `agent/tests/test_agent_api.py`, `test_agent_checkpoint.py` | Agent HTTP API, streaming/checkpoint behavior |
| `agent/tests/test_client_context.py`, `test_message_history.py` | Client context and checkpoint-backed transcript history |
| `agent/tests/test_layout_hash.py`, `test_layout_sync.py`, `test_map_set_viewport.py` | Layout hashing/sync and map viewport tool behavior |
| `agent/tests/test_user_actions.py`, `test_dev_reset.py` | User actions and development reset behavior |

Run unit tests: `uv run pytest -m unit` (same as pre-commit). Integration: `uv run pytest -m integration`. Benchmarks: `uv run pytest benchmarks/ -m benchmark`.

## Configuration

- `.env-template` — env vars by module namespace (`GMAPS_QUOTA_*`, `GMAPS_CACHE_*`, `GMAPS_REQUESTS_BASE_*`)
- `pyproject.toml` — hatchling wheel (`gmaps`), pytest markers

## Human docs

| Path | Audience |
|------|----------|
| [`docs/agent-api.md`](docs/agent-api.md) | Agent HTTP **v1** — `/chat`, SSE stream events |
| [`docs/gmaps-client.md`](docs/gmaps-client.md) | Integrators using `gmaps` |
| [`docs/google-maps-pricing.md`](docs/google-maps-pricing.md) | Pricing matrix for Google Maps endpoints used by FOGG |
| [`docs/domain/domain-model.md`](docs/domain/domain-model.md) | User / trip / itinerary / activity / place / route / versioning; **secrets** device-local first |
| [`docs/domain/schema.dbml`](docs/domain/schema.dbml) | Postgres + PostGIS (**DBML**) |
| [`docs/domain/geospatial.md`](docs/domain/geospatial.md) | PostGIS geom, event impact queries |
| [`docs/latency-optimization.md`](docs/latency-optimization.md) | Latency UX, baselines, system perf test matrix |

Use **Postman** (Google Maps Platform workspace) for API exploration — not checked into this repo.

## Cursor / review

- **Collaboration:** `.cursor/rules/collaboration.mdc`
- **Commits:** `.cursor/rules/git-commits.mdc` (Conventional Commits)
- **Python review:** `.cursor/skills/python-code-review/SKILL.md` — update **this file** when layout or entrypoints change; report findings in the review reply

## Agents directory

[`agent/`](agent/README.md) — LangGraph ReAct harness (`master_agt` package at `agent/src/master_agt/`). From **repo root**: `uv sync`; optional `cp agent/.env-template agent/.env`; `uv run uvicorn api.app:app` (or `./scripts/run-agent-debug.sh`). API contract: [`docs/agent-api.md`](docs/agent-api.md). Package map (under `agent/src/`):

| Module | Role |
|--------|------|
| `api/routes/` | `/v1` health and user-scoped chat, SSE, messages, layout, and user-actions; `chat_handlers.py` and `chat_messages.py` split chat orchestration/history routes |
| `master_agt/` | Master travel agent prompts, state, nodes, tools, and lazy `get_graph()` |
| `browser_agt/` | Task-scoped research graph/service, remote Unix-socket browser client, Chromium worker, and runtime |
| `agent_utils/` | Shared database URL, environment loading, request context, checkpointer, model factory/token counting, and LangGraph node builders |
| `gmaps/` | Google Maps client package (import name: `gmaps`) |
| `api/app.py`, `api/main.py`, `api/routes/`, `api/messages/` | FastAPI service/lifespan, Uvicorn entrypoints, HTTP routes, and transcript endpoint handling |
| `api/dev_reset.py` | Development-only data reset behavior |
| `layout/` | Postgres layout rows, models, hashing/sync rules, client context, user actions, and `map_set_viewport` tool implementation (`_tool.py`) |
| `api/messages/store.py` | Checkpoint-backed transcript history for the client |
| `agent_utils/checkpointing.py` | `AsyncPostgresSaver` checkpointer |

LangGraph Studio: `cd agent && uv run langgraph dev` (needs Postgres URL like uvicorn).

### Docker (Redis + Postgres + Ollama + Phoenix + master, research, browser worker, and proxy services)

Both `full` and `debug-agent` profiles include local Phoenix tracing, available at
`http://127.0.0.1:16006` by default (`COMPOSE_PORT_PHOENIX`). Trace data persists
in the `phoenix_data` volume. The agent exports LangGraph spans using
`agent_utils/tracing.py`; see the [agent README](agent/README.md#local-phoenix-traces)
for settings and how to disable tracing.

From **repo root**: `./scripts/compose-up.sh full --build` (or **`debug-agent`** + **`scripts/run-agent-debug.sh`** for host agent with reload; **`--list-profiles`**). **Ollama** uses **`gpus: all`** (needs [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html); see [`deploy/README.md`](deploy/README.md)) — comment that line out for CPU-only. Published host ports default to **16379** (redis), **15432** (postgres), **11434** (Ollama), **18080** (agent), **18000** (backend stub) — override with `COMPOSE_PORT_*` in [`.env`](deploy/compose.env.example). The Svelte dev server reads **`FRONTEND_WEB_PORT_DEBUG`** and **`AGENT_API_BASE_URL`** from root **`.env`**. The stack includes **Ollama**; the agent container gets **`COMPOSE_AGENT_OPENAI_BASE_URL`** (default **`http://ollama:11434/v1`**) mapped to **`OPENAI_BASE_URL`**, so host **`.env`** `OPENAI_BASE_URL` does not break Docker. For host-only Ollama: `COMPOSE_AGENT_OPENAI_BASE_URL=http://host.docker.internal:11434/v1`. Local agent (no Docker): `127.0.0.1:11434`.

The isolated browser worker runs headed Google Chrome under Xvfb. It has no Docker network; browser egress still passes through `browser-proxy`. Its dedicated persistent profile lives in the Docker `browser_profile` volume and is shared serially across research jobs. Never mount a personal desktop Chrome profile into the worker.
