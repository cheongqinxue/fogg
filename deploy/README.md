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
| `agent`    | `COMPOSE_PORT_AGENT` (18080) | `AGENT_INTERNAL_PORT` (8080) | `api.app` |
| `backend`  | `COMPOSE_PORT_BACKEND` (18000) | `BACKEND_INTERNAL_PORT` (8000) | [`backend/server.py`](../backend/server.py) stub |

**Run**

```bash
cp deploy/compose.env.example .env   # edit COMPOSE_PORT_* if needed
./scripts/compose-up.sh full --build        # agent in Docker
./scripts/compose-up.sh --list-profiles     # profiles + usage
```

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
