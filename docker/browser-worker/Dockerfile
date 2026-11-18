FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
WORKDIR /app
RUN pip install --no-cache-dir uv
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates gnupg wget xvfb xauth libatomic1 \
    && wget -qO- https://dl.google.com/linux/linux_signing_key.pub \
       | gpg --dearmor -o /usr/share/keyrings/google-chrome.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/google-chrome.gpg] https://dl.google.com/linux/chrome/deb/ stable main" \
       > /etc/apt/sources.list.d/google-chrome.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends google-chrome-stable \
    && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml uv.lock README.md ./
COPY agent/src/browser_agt ./agent/src/browser_agt
RUN uv sync --frozen --no-dev --no-install-project \
    && uv run --no-sync playwright install-deps chromium \
    && uv run --no-sync playwright install ffmpeg \
    && groupadd --gid 10001 browser \
    && useradd --create-home --uid 10001 --gid 10001 browser \
    && mkdir -p /run/fogg-browser /run/browser-proxy /recordings /browser-profile \
    && chown -R 10001:10001 /app /ms-playwright /run/fogg-browser /run/browser-proxy /recordings /browser-profile

ENV PYTHONPATH=/app/agent/src
ENV HOME=/tmp BROWSER_WORKER_SOCKET=/run/fogg-browser/worker.sock
USER 10001:10001
CMD ["xvfb-run", "-a", "--server-args=-screen 0 1440x1000x24 -nolisten tcp", "uv", "run", "--no-sync", "python", "-m", "browser_agt.worker"]
