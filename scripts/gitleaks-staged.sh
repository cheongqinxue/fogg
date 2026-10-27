#!/usr/bin/env bash
# Pre-commit: scan staged changes for secrets (uses project-local binary when present).
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
LOCAL_BIN="${ROOT}/.tools/gitleaks/gitleaks"
CONFIG="${ROOT}/.gitleaks.toml"

if [[ -x "${LOCAL_BIN}" ]]; then
  GITLEAKS="${LOCAL_BIN}"
elif command -v gitleaks >/dev/null 2>&1; then
  GITLEAKS="$(command -v gitleaks)"
else
  echo "gitleaks not found. Install to .tools: see setup.sh or scripts/install-gitleaks.sh" >&2
  exit 1
fi

exec "${GITLEAKS}" protect --staged --verbose --redact -c "${CONFIG}"
