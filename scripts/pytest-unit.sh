#!/usr/bin/env bash
# Pre-commit / fast CI: run only tests marked ``unit``.
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
cd "${ROOT}"

LOCAL_UV="${ROOT}/.tools/uv/uv"
if [[ -x "${LOCAL_UV}" ]]; then
  exec "${LOCAL_UV}" run pytest -m unit "$@"
fi
if command -v uv >/dev/null 2>&1; then
  exec uv run pytest -m unit "$@"
fi

echo "uv not found. Run ./setup.sh or add uv to PATH." >&2
exit 1
