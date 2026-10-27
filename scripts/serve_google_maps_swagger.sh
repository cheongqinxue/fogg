#!/usr/bin/env bash
# Local Swagger UI for docs/google-maps-api (no Docker required).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PORT="${PORT:-8765}"
echo "Swagger UI: http://127.0.0.1:${PORT}/swagger/"
echo "Press Ctrl+C to stop."
exec python3 -m http.server "$PORT" --directory "$ROOT/docs/google-maps-api"
