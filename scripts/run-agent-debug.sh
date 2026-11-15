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
: "${FOGG_TRACING_ENDPOINT:=http://127.0.0.1:${COMPOSE_PORT_PHOENIX}/v1/traces}"

export OPENAI_BASE_URL REDIS_URL AGENT_DATABASE_URL AGENT_DEV_RESET_ENABLED FOGG_TRACING_ENABLED FOGG_TRACING_ENDPOINT

exec uv run uvicorn api.app:app \
  --reload \
  --host 127.0.0.1 \
  --port "${AGENT_INTERNAL_PORT}"
