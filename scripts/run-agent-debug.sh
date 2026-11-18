#!/usr/bin/env bash
# Run the LangGraph FastAPI agent on the host (reload). Use with compose profile debug-agent.
#
# Expects stack up: ./scripts/compose-up.sh debug-agent
# Defaults OPENAI_BASE_URL to host-published Ollama (COMPOSE_PORT_OLLAMA / 11434).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

set -a
# shellcheck disable=SC1091
if [[ -f "$REPO_ROOT/.env" ]]; then
  . "$REPO_ROOT/.env"
fi
set +a

: "${COMPOSE_PORT_OLLAMA:=11434}"
: "${COMPOSE_PORT_REDIS:=16379}"
: "${COMPOSE_PORT_POSTGRES:=15432}"
: "${AGENT_INTERNAL_PORT:=18080}"
: "${OPENAI_BASE_URL:=http://127.0.0.1:${COMPOSE_PORT_OLLAMA}/v1}"
: "${REDIS_URL:=redis://127.0.0.1:${COMPOSE_PORT_REDIS}/0}"
: "${AGENT_DATABASE_URL:=postgresql://fogg:fogg@127.0.0.1:${COMPOSE_PORT_POSTGRES}/fogg}"
: "${AGENT_DEV_RESET_ENABLED:=true}"
: "${FOGG_TRACING_ENABLED:=true}"
: "${COMPOSE_PORT_PHOENIX:=16006}"
: "${COMPOSE_PORT_BROWSER_RESEARCH:=18081}"
: "${BROWSER_AGENT_SERVICE_TOKEN:=}"
: "${BROWSER_AGENT_SERVICE_TIMEOUT_SECONDS:=320}"
: "${BROWSER_AGENT_MODEL:=hf.co/Mungert/UI-TARS-1.5-7B-GGUF:Q4_K_M}"
: "${BROWSER_AGENT_OLLAMA_URL:=http://127.0.0.1:${COMPOSE_PORT_OLLAMA}/api/chat}"
: "${BROWSER_AGENT_CONTEXT_LENGTH:=32768}"
: "${FOGG_TRACING_ENDPOINT:=http://127.0.0.1:${COMPOSE_PORT_PHOENIX}/v1/traces}"

if [[ -z "$BROWSER_AGENT_SERVICE_TOKEN" ]]; then
  echo "Set BROWSER_AGENT_SERVICE_TOKEN in .env (generate with: openssl rand -hex 32)" >&2
  exit 2
fi

if [[ -z "${BROWSER_AGENT_SERVICE_URL:-}" ]]; then
  BROWSER_AGENT_SERVICE_URL="$(COMPOSE_PORT_BROWSER_RESEARCH="$COMPOSE_PORT_BROWSER_RESEARCH" uv run python -c 'import asyncio, os; from agent_utils.browser_endpoint import local_browser_service_url; print(asyncio.run(local_browser_service_url(int(os.environ["COMPOSE_PORT_BROWSER_RESEARCH"]))))')"
fi

export OPENAI_BASE_URL REDIS_URL AGENT_DATABASE_URL AGENT_DEV_RESET_ENABLED FOGG_TRACING_ENABLED FOGG_TRACING_ENDPOINT
export BROWSER_AGENT_SERVICE_URL BROWSER_AGENT_SERVICE_TOKEN BROWSER_AGENT_SERVICE_TIMEOUT_SECONDS
export BROWSER_AGENT_MODEL BROWSER_AGENT_OLLAMA_URL BROWSER_AGENT_CONTEXT_LENGTH

exec uv run uvicorn api.app:app \
  --reload \
  --host 127.0.0.1 \
  --port "${AGENT_INTERNAL_PORT}"
