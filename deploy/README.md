# Docker Compose (local stack)

- **Compose file:** [`docker-compose.yml`](../docker-compose.yml) at repo root
- **Env template:** [`compose.env.example`](compose.env.example) — copy to **`.env`** in repo root

**GPU (Ollama):** **`ollama` has `gpus: all`** — install [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html) (and an NVIDIA driver). If Compose fails with *could not select device driver … \[\[gpu\]\]*, comment out **`gpus: all`** under **`ollama`** in `docker-compose.yml` for CPU-only inference.

**Services**

| Service    | Default host port | In-container | Role |
|------------|-------------------|--------------|------|
| `redis`    | `COMPOSE_PORT_REDIS` (16379) | 6379 | Cache / queues |
| `postgres` | `COMPOSE_PORT_POSTGRES` (15432) | 5432 | PostGIS |
| `ollama`   | `COMPOSE_PORT_OLLAMA` (11434) | 11434 | LLM runtime (models in `.data/ollama_data`) |
| `agent`    | `COMPOSE_PORT_AGENT` (18080) | `AGENT_INTERNAL_PORT` (8080) | Master `api.app`, no Chromium binary |
| `browser-research` | internal only in `full`; loopback only in `debug-agent` | 18081 | Authenticated research graph/model service |
| `browser-worker` | none | Unix socket only | Sandboxed Chromium jobs; `network_mode: none` |
| `browser-proxy` | none | Unix socket only | Validates and pins public egress destinations |
| `backend`  | `COMPOSE_PORT_BACKEND` (18000) | `BACKEND_INTERNAL_PORT` (8000) | [`backend/server.py`](../backend/server.py) stub |

**Run**

```bash
cp deploy/compose.env.example .env   # edit COMPOSE_PORT_* if needed
./scripts/compose-up.sh full --build        # agent and private browser stack in Docker
./scripts/compose-up.sh --list-profiles     # profiles + usage
```

Before starting either profile, set these values in `.env`:

```dotenv
BROWSER_AGENT_SERVICE_TOKEN=<output of openssl rand -hex 32>
BROWSER_PROXY_DENY_HOSTS=<comma-separated host IPs and deployment service CIDRs>
```

The proxy deny list must include the deployment host's addresses and any public or
private service ranges that the proxy must not reach. The proxy rejects private,
loopback, link-local, and other non-public targets and pins DNS results; this does
not identify a deployment's own public addresses. In production, also enforce
egress filtering outside Docker so infrastructure addresses cannot be reached
through overlooked routes.

The browser worker has no non-loopback network interface, no TCP listener on a container
interface, no application credentials, a read-only root filesystem, a non-root
UID, Chromium's sandbox, and bounded CPU, memory, process count, task time, and
browser actions. Its only egress path is a loopback TCP relay that forwards to the
proxy's Unix socket. Chromium is configured to use that proxy explicitly, bypass
loopback proxy bypass behavior, and disable QUIC. The research service and master
communicate over HTTP; the worker speaks a bounded JSON-lines protocol over a
private Unix socket, one connection and browser context per task. Closing or
losing that connection closes the browser context. No worker or proxy port is
published to the host.

The defaults are 90 seconds per research task, 20 graph steps, 30 browser actions,
10 seconds per browser operation and two concurrent research tasks. Each browser
navigation, observation, click, fill or back action counts separately. Operators
can configure `BROWSER_AGENT_TASK_TIMEOUT_SECONDS`, `BROWSER_AGENT_MAX_CONCURRENT_TASKS`,
`BROWSER_WORKER_MAX_TASK_SECONDS`, `BROWSER_WORKER_ACTION_LIMIT`, and
`BROWSER_WORKER_OPERATION_TIMEOUT_MS`; the worker rejects values outside its hard
limits. The proxy caps each HTTPS tunnel direction at 64 MiB, not individual
decrypted responses, and allows at most 64 concurrent connections by default.

Chromium runs with its own sandbox. `browser-worker` uses
[`chromium-seccomp.json`](chromium-seccomp.json), pinned from Microsoft's
Playwright repository at commit
[`354e6fa33a899f8e0ee1ef5428eaf9a934378615`](https://github.com/microsoft/playwright/commit/354e6fa33a899f8e0ee1ef5428eaf9a934378615).
It is the Docker default seccomp profile with Playwright's additional allow rule
for `clone`, `setns`, and `unshare`, plus `chroot` for Chromium's namespace-local
sandbox setup. The worker drops all container capabilities, so the added seccomp
permission does not itself grant host-level chroot privilege. It does not use
`seccomp=unconfined`. Chromium startup was smoke-tested on the development host
with the worker's network, filesystem, capability and seccomp restrictions; other
hosts must also support unprivileged user namespaces.

`debug-agent` requests a loopback-only published research endpoint. On Linux Docker,
services connected only to internal networks can have no published binding; in
that case `scripts/run-agent-debug.sh` discovers the research container's bridge
address for the host-run master. Set the same service token in `.env`; the script
loads it. On hosts that cannot reach Docker bridge addresses directly, provide a
reachable `BROWSER_AGENT_SERVICE_URL` explicitly.

After starting the stack, `uv run pytest agent/tests/test_browser_deployment.py -m integration`
checks the worker's network mode, confirms its proxy rejects a loopback destination,
and opens a blank page through the worker socket. The check makes no paid API calls.
The remaining browser tests run offline with `uv run pytest -m unit`.

**Agent on host (no container rebuild):**

```bash
./scripts/compose-up.sh debug-agent
./scripts/run-agent-debug.sh   # uvicorn --reload on 127.0.0.1:8080
```

Or plain `docker compose up ollama redis postgres backend agent` / omit `agent` manually. New profiles: edit `compose_profile_services()` in [`scripts/compose-up.sh`](../scripts/compose-up.sh).

Both profiles include local Phoenix tracing at `http://127.0.0.1:16006` (port
`COMPOSE_PORT_PHOENIX`). Trace data persists in the `phoenix_data` volume; see
the [agent README](../agent/README.md#local-phoenix-traces) for configuration.

- **Agent HTTP:** `http://127.0.0.1:$COMPOSE_PORT_AGENT/v1/...` (default **18080**; e.g. **`/v1/health`**, **`/v1/users/{user_id}/chat/stream`**)
- **Backend HTTP:** `http://127.0.0.1:$COMPOSE_PORT_BACKEND` (default **18000**)
- **Ollama API from your host:** `http://127.0.0.1:$COMPOSE_PORT_OLLAMA` (default **11434**). Pull the model once: `docker compose exec ollama ollama pull lfm3:1.7b`
- **Redis / Postgres from your host** (psql, DBeaver): `127.0.0.1:$COMPOSE_PORT_REDIS`, `127.0.0.1:$COMPOSE_PORT_POSTGRES` — **containers** still use `redis:6379` and `postgres:5432` in `REDIS_URL` / `DATABASE_URL`.

**LLM URL:** the agent container gets **`OPENAI_BASE_URL`** from **`COMPOSE_AGENT_OPENAI_BASE_URL`** (default **`http://ollama:11434/v1`**). Root **`.env`** often sets **`OPENAI_BASE_URL`** for local Python — that is **not** used for compose substitution on this key, so the in-stack Ollama URL still wins. For host Ollama: `COMPOSE_AGENT_OPENAI_BASE_URL=http://host.docker.internal:11434/v1`. Use **`AGENT_OPENAI_API_KEY`** in `.env` so it does not pick up your host **`OPENAI_API_KEY`**.
