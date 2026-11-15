# API stub until the real backend lands — shares root lockfile.
FROM python:3.12-slim-bookworm

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock README.md ./
COPY backend/__init__.py backend/server.py ./backend/
COPY agent/src/graph ./agent/src/graph

RUN uv sync --frozen --no-dev

COPY . .

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app
ENV REDIS_URL=

ENV BACKEND_INTERNAL_PORT=8000
EXPOSE 8000

CMD ["sh", "-c", "uv run uvicorn backend.server:app --host 0.0.0.0 --port ${BACKEND_INTERNAL_PORT:-8000}"]
