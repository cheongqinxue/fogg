# LangGraph ReAct agent (this repo)

[LangGraph application layout](https://docs.langchain.com/oss/python/langgraph/application-structure): Python package **`master_agt/`** at **`agent/src/master_agt/`**, **`langgraph.json`** in **`agent/`**, Bruno under **`agent/bruno/`**.

The **`master_agt`** package is included in the **repository root** `uv` project (`pyproject.toml` hatch sources map `agent/src/master_agt` → import name `master_agt`). Use **one venv at repo root** — no separate `agent/pyproject.toml`.

Model backend: **OpenAI-compatible API** via **`ChatOpenAI`**. Defaults: **Ollama** + **LFM3 1.7B** (`lfm3:1.7b`). Same code path works for **vLLM** / **SGLang** — change **`OPENAI_BASE_URL`** and **`AGENT_MODEL`**.

## Prerequisite: Ollama

```bash
ollama pull lfm3:1.7b
ollama serve   # default http://127.0.0.1:11434
```

Quantized variant: `lfm3:1.7b-q4_K_M` — set `AGENT_MODEL` accordingly.

## Setup

From **repository root**:

```bash
uv sync
cp .env-template .env
# set FRONTEND_WEB_PORT_* and AGENT_API_BASE_URL; copy agent section to agent/.env for LangGraph dev
```

**LangGraph CLI** (`cd agent && uv run langgraph dev`) reads **`agent/.env`** only — duplicate relevant vars there if needed.

## Run (FastAPI)

From **repository root** (uses root `.env` if your shell exports it, or prefix vars):

```bash
uv run uvicorn api.app:app --reload --host 127.0.0.1 --port "${AGENT_INTERNAL_PORT:-8080}"
# alternate entry: uv run uvicorn api.main:app
```

With Docker for Ollama/Redis/Postgres (no agent container): **`./scripts/compose-up.sh debug-agent`**, then:

```bash
./scripts/run-agent-debug.sh          # repo root
# or
./agent/scripts/run-api-reload.sh     # same thing
```

- `GET /v1/health` — liveness
- `POST /v1/users/{user_id}/chat` — JSON `{"message":"...", "client_context": optional}` — one full turn
- `POST /v1/users/{user_id}/chat/stream` — same body, **SSE** (`text/event-stream`): `tool_call_start` (`name`, `arguments`, `run_id`), `tool_call_end` (`name`, `arguments`, `output`, `tool_call_id?`), `assistant_delta`, then `assistant_done`
- `GET /v1/users/{user_id}/messages` — user/assistant transcript for UI restore
- Layout and map: `GET|POST /v1/users/{user_id}/layout…`, `POST …/user-actions`

Full request/response reference: [`docs/agent-api.md`](../docs/agent-api.md).

**Bruno:** [Open Collection](https://docs.usebruno.com/get-started/bruno-basics/open-collection) → [`bruno/FOGG-Agent`](bruno/FOGG-Agent). Pick environment **`local`** (host agent on **8080**) or **`docker`** (**18080**). Requests under **v1/**.

**CORS:** `CORS_ORIGINS` (comma-separated) or `*` (default). Tighten in staging/production.

## Run (LangGraph CLI — optional, Studio)

```bash
cd agent
uv run langgraph dev
```

`langgraph.json` loads `agent/.env` if present. API defaults to `http://127.0.0.1:2024` when the CLI starts.

## Invoke in Python

```python
from master_agt.agent import graph  # lazy singleton

result = await graph.ainvoke(
    {"messages": [("user", "Say hello and use echo_destination for Paris.")]}
)
```

## Streaming

Use `graph.astream()` or `graph.astream_events()` on the compiled graph (see LangGraph docs).

## Environment

| Variable | Purpose |
|----------|---------|
| `OPENAI_BASE_URL` | OpenAI-compatible root, default **`http://127.0.0.1:11434/v1`** (Ollama); vLLM/SGLang use their `/v1` base |
| `OPENAI_API_KEY` | Sent as `Authorization`; Ollama ignores it — default `ollama` |
| `AGENT_MODEL` | Server model id (default `lfm3:1.7b`) |
| `AGENT_DATABASE_URL` / `DATABASE_URL` | Postgres for LangGraph thread checkpoints (required) |
| `CORS_ORIGINS` | FastAPI CORS: `*` or comma-separated origins |
| `AGENT_INTERNAL_PORT` | Uvicorn listen port when run locally (match `AGENT_API_BASE_URL`) |

## Layout

```
agent/
├── bruno/FOGG-Agent/
├── langgraph.json
└── src/
    ├── master_agt/  # Master LangGraph harness, prompt, state, nodes, and tools
    ├── browser_agt/ # Browser research graph and task-scoped Playwright runtime
    ├── api/         # FastAPI app, routes, transcript endpoints, dev reset
    ├── layout/      # independent layout functionality (store, sync, map tool)
    ├── gmaps/       # Google Maps client functionality; import name remains gmaps
    └── agent_utils/ # shared DB, model, LangGraph nodes, checkpoint, and context helpers
```

Agent, layout, and Maps client tests live in **`agent/tests/`** (imports include `master_agt.*`, `browser_agt.*`, `agent_utils.*`, `api.*`, `layout.*`, and `gmaps.*`).

### Browser research

Each browser task records a Playwright trace, a WebM video, and a periodically
updated preview frame in its own directory on the `browser_recordings` Docker
volume. To watch active sessions locally, start the stack and run:

```bash
uv run python scripts/watch-browser.py
```

Open `http://127.0.0.1:18083` and select a session. The read-only preview refreshes
approximately twice per second; it is not a remote-control interface. To export
recordings from the running worker to the Git-ignored `.data/browser-recordings/`:

```bash
bash scripts/export-browser-recordings.sh
uv run playwright show-trace .data/browser-recordings/<session-id>/trace.zip
```

The WebM video is finalized when the browser context closes. The trace is a
Playwright action/snapshot history; Phoenix retains the agent/model trace separately.
Recordings can contain page data and requests, persist on the Docker volume, and are
not automatically deleted. They may be incomplete if the worker is killed abruptly.

For local browser compatibility testing, `BROWSER_USER_AGENT`,
`BROWSER_ACCEPT_LANGUAGE`, `BROWSER_DNT`, `BROWSER_SEC_CH_UA`,
`BROWSER_SEC_CH_UA_MOBILE`, and `BROWSER_SEC_CH_UA_PLATFORM` optionally override
the browser context's identity headers. Empty values leave Playwright's defaults.
These settings do not change Chromium's engine, cookies, or automation fingerprint;
request-specific headers such as `Accept`, `Referer`, and `Sec-Fetch-*` are still
determined by the actual request.

The master delegates focused public-web research to `research_web` over the private browser research service (`browser_agt.service:app`). The master connects to its authenticated `WS /duplex` endpoint and keeps the connection open for the task. After each page observation, the browser sends a compact update (URL, title, excerpt, and scroll signals); the master model considers it and replies with steering or `CONTINUE`. The browser also has a `browser_ask_master` tool for explicit questions when it needs trip context or a judgment call. The browser receives master guidance in tool results. This adds one master-model inference per browser observation. The service runs UI-TARS-1.5 as its visual browser controller. Each browser model turn receives the page screenshot plus page text; UI-TARS returns bounded coordinate actions that run in the isolated headed Chrome worker over its Unix socket. The master requires `BROWSER_AGENT_SERVICE_TOKEN` and sends it as a bearer token; configure the same random secret on both processes. Set `BROWSER_AGENT_SERVICE_URL` on the master (default `http://127.0.0.1:18081`) and `BROWSER_AGENT_SERVICE_TIMEOUT_SECONDS` (default 320). The service allows up to 300 seconds per task (`BROWSER_AGENT_TASK_TIMEOUT_SECONDS`) and 80 LangGraph steps; the browser worker task limit (`BROWSER_WORKER_MAX_TASK_SECONDS`) is also 300 seconds, with at most 80 browser operations. Each master chat turn can call browser research at most twice: one initial request and one focused follow-up. The worker serializes access to its persistent profile. Excess concurrent work is rejected with WebSocket close code 4429; default capacity is one. There is no in-process fallback. Browser-model settings are `BROWSER_AGENT_MODEL` (default `hf.co/Mungert/UI-TARS-1.5-7B-GGUF:Q4_K_M`), `BROWSER_AGENT_OLLAMA_URL`, `BROWSER_AGENT_CONTEXT_LENGTH` (default 32768), and `BROWSER_AGENT_MAX_INPUT_TOKENS`. The host debug runner points to host Ollama; Compose uses its bundled Ollama service and pulls the configured master and browser models during startup. Configure the same `FOGG_TRACING_ENABLED`, `FOGG_TRACING_ENDPOINT`, and `FOGG_TRACING_PROJECT` values on the agent and research service to keep their LangGraph spans in the same Phoenix project; W3C trace context is propagated for each research task. Search starts with DuckDuckGo. Browser graph intermediate events are retained for tracing but are not streamed as master-agent text. When research is partial but has useful sources, the master can make one focused follow-up request for the missing facts.

The browser worker runs headed Google Chrome under Xvfb, behind the same mandatory egress proxy and without a Docker network interface. Its dedicated Chrome user-data directory is stored in the Docker `browser_profile` volume; cookies and other browser session data therefore persist between jobs. Do not mount or copy your everyday Chrome profile into this worker. Browser recordings and screenshots remain available through `scripts/watch-browser.py` and `scripts/export-browser-recordings.sh`.

Browser observations carry task-scoped IDs and JPEG screenshots. The model context
keeps at most the two most recently exposed observations in full; older tool results
retain a reference with the ID, URL, and title. Historical screenshots and DOM text
are omitted from model context after that point. UI-TARS uses the screenshots for
visual decisions and interacts through bounded screenshot coordinates. Full
observations remain available to the active research run and its trace recording.
Observations report the active document or nested scroll container's dimensions and
position, whether it is at its end, whether a scroll changed its position, and whether
the screenshot changed perceptibly since the previous observation.

Each UI-TARS inference emits a compact `ui_tars.turn` Phoenix span with its
`Thought`, parsed action/tool call, and the latest observation ID, URL, title, and
screenshot-present flag. It never includes screenshot bytes. The browser research
service hides LangChain span inputs and outputs (`FOGG_TRACING_HIDE_IO=true`) so
base64 screenshots cannot overwhelm Phoenix; compact UI-TARS spans remain visible
for diagnosing repeated or incorrect actions.

For host development, run `uv run playwright install chromium` and install Playwright's system dependencies where needed. The agent image installs Chromium and runs as a non-root user; Chromium sandboxing must be supported by the host and container security configuration. The current browser policy blocks non-public addresses and non-read HTTP methods, but DNS rebinding and state-changing GET requests remain possible. Before exposing browser research to untrusted users or websites, deploy the browser in a separately isolated worker with network egress controls that prevent access to private services; the application-level checks alone do not provide that isolation. UI-TARS controls only the current browser through the supported read-oriented action set; it does not bypass worker network or action policies.

# Simulated agent scenario

With `FOGG_ENV=dev`, the agent replaces Google Maps tools with simulations.
All entries in `master_agt/simulations/__init__.py` are available simultaneously.
Each case maps expected argument values to a response. Expectations support
regular expressions, nested dictionaries, inclusive numeric ranges, and a
geographic center with a maximum distance. Unmatched calls return a tool error;
they never reach Google. Original tool schemas and validation are preserved.
The Nagano resort fixtures are fictional. Local tools such as map viewport
remain active. Restart the agent after changing the environment or scenarios.
Simulated external tool calls wait asynchronously for one second, including
unmatched calls. Tests or custom graphs can override this with the
`delay_seconds` argument to `simulated_tools`.
The Nagano scenario includes fictional driving responses from Shinshu
Matsumoto Airport to the three fictional ski locations. Their encoded
polylines are straight lines, and their durations and distances are sample data,
not navigable routes or travel estimates.

Text and nearby search use fixed Pro-tier field masks defined in
`gmaps/requests/search_fields.py`; the agent does not choose the mask. Fields
include place identity, names, coordinates and other Pro data where available.
Ratings and reviews require higher tiers and are not in these search responses.
Place Details also uses a fixed Pro-tier mask. Route and route-matrix tools use
fixed masks for route, leg, and step details, geometry, and matrix status; route
optimization additionally requests the optimized waypoint order. Route request
features such as traffic awareness and waypoint optimization can select a
higher billing tier even with these fixed masks.

Compose configures Ollama with a 32,768-token context by default. The master
agent input budget defaults to an estimated 20,000 tokens; browser research
defaults to 32,000, leaving 768 tokens of the UI-TARS context for generation.
Browser context preparation preserves the original request and latest screenshot,
then trims older observations and actions to fit. Configure
`OLLAMA_CONTEXT_LENGTH`, `AGENT_MAX_INPUT_TOKENS`, and
`BROWSER_AGENT_MAX_INPUT_TOKENS` for the model and hardware in use. Older graph
messages are trimmed from model input while checkpoints remain intact. Token
counts are approximate and do not guarantee a model-specific context limit.

## Local Phoenix traces

The `debug-agent` and `full` Compose profiles start Phoenix with persistent
storage. Open `http://127.0.0.1:16006` (or `COMPOSE_PORT_PHOENIX`) to inspect
the `fogg-dev` project's agent, model, and tool spans. The host debug script
and container agent enable tracing by default. Set `FOGG_TRACING_ENABLED=false`
to disable it; set `FOGG_TRACING_PROJECT` to change the project. Host agents
use `FOGG_TRACING_ENDPOINT`; containers use `COMPOSE_AGENT_TRACING_ENDPOINT`
to set their respective OTLP HTTP endpoint, including `/v1/traces`.

Phoenix stores traces in the `phoenix_data` Docker volume. Traces include
conversation text and tool inputs and outputs. A failed trace export does not
prevent an agent request from running; spans are buffered and exported in the
background. They may be lost if Phoenix is unavailable or the process exits
abruptly.
