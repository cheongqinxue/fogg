FROM python:3.12-slim-bookworm

WORKDIR /app

RUN pip install --no-cache-dir "h11>=0.16,<1" "yarl>=1.18,<2" \
    && useradd --create-home --uid 10001 fogg \
    && mkdir -p /run/browser-proxy \
    && chown fogg:fogg /run/browser-proxy

COPY agent/src/browser_proxy ./browser_proxy

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app
ENV BROWSER_PROXY_SOCKET_PATH=/run/browser-proxy/proxy.sock

USER fogg
CMD ["python", "-m", "browser_proxy.server"]
