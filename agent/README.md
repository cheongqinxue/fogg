# LangGraph ReAct agent (this repo)

[LangGraph application layout](https://docs.langchain.com/oss/python/langgraph/application-structure): Python package **`master_agt/`** at **`agent/src/master_agt/`**, **`langgraph.json`** in **`agent/`**, Bruno under **`agent/bruno/`**.

The **`graph`** package is included in the **repository root** `uv` project (`pyproject.toml` hatch sources map `agent/src/master_agt` → import name `master_agt`). Use **one venv at repo root** — no separate `agent/pyproject.toml`.

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

result = graph.invoke(
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
    ├── master_agt/       # LangGraph harness, graph state/tools, checkpoint integration
    ├── api/         # FastAPI app, routes, transcript endpoints, dev reset
    ├── layout/      # independent layout functionality (store, sync, map tool)
    ├── gmaps/       # Google Maps client functionality; import name remains gmaps
    └── agent_utils/ # shared DB, environment, and request-context helpers
```

Agent, layout, and Maps client tests live in **`agent/tests/`** (imports include `master_agt.*`, `api.*`, `layout.*`, and `gmaps.*`).

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

The model input budget defaults to an estimated 20,000 tokens, leaving room in
the default 32,768-token Ollama context for tool schemas and generation. Set
`AGENT_MAX_INPUT_TOKENS` to suit the actual model context. Older graph messages
are trimmed from model input while checkpoints remain intact. The token count
is approximate and does not guarantee a model-specific context limit.

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
