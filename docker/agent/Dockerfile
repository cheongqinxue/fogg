# LangGraph / FastAPI agent — same deps as repo root (uv lockfile).
FROM python:3.12-slim-bookworm

WORKDIR /app

RUN pip install --no-cache-dir uv

# Resolve deps first for layer cache (hatch needs readme = README.md)
COPY pyproject.toml uv.lock README.md ./
COPY agent/src/gmaps ./agent/src/gmaps
COPY agent/src/layout ./agent/src/layout
COPY agent/src/api ./agent/src/api
COPY agent/src/agent_utils ./agent/src/agent_utils
COPY agent/src/master_agt ./agent/src/master_agt

RUN uv sync --frozen --no-dev

COPY . .

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app
# Redis URL for future cache / LangGraph (compose injects REDIS_URL)
ENV REDIS_URL=

ENV AGENT_INTERNAL_PORT=8080
EXPOSE 8080

# Compose sets AGENT_INTERNAL_PORT to match the right side of ports: mapping.
CMD ["sh", "-c", "uv run uvicorn api.app:app --host 0.0.0.0 --port ${AGENT_INTERNAL_PORT:-8080}"]
