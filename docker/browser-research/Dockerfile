FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN pip install --no-cache-dir uv
COPY pyproject.toml uv.lock README.md ./
COPY agent/src/browser_agt ./agent/src/browser_agt
COPY agent/src/agent_utils ./agent/src/agent_utils
RUN uv sync --frozen --no-dev --no-install-project \
    && groupadd --gid 10001 fogg \
    && useradd --create-home --uid 10001 --gid 10001 fogg \
    && chown -R 10001:10001 /app

ENV PYTHONPATH=/app/agent/src HOME=/tmp
USER 10001:10001
EXPOSE 18081
CMD ["uv", "run", "--no-sync", "uvicorn", "browser_agt.service:app", "--host", "0.0.0.0", "--port", "18081"]
