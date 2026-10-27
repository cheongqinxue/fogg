#!/usr/bin/env bash
# Install gitleaks binary into .tools/gitleaks/ (gitignored).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="${GITLEAKS_VERSION:-8.22.1}"
DEST="${ROOT}/.tools/gitleaks"
ARCH="$(uname -m)"

case "${ARCH}" in
  x86_64) ASSET="gitleaks_${VERSION}_linux_x64.tar.gz" ;;
  aarch64 | arm64) ASSET="gitleaks_${VERSION}_linux_arm64.tar.gz" ;;
  *)
    echo "Unsupported arch: ${ARCH}. Install gitleaks manually and ensure it is on PATH." >&2
    exit 1
    ;;
esac

URL="https://github.com/gitleaks/gitleaks/releases/download/v${VERSION}/${ASSET}"
mkdir -p "${DEST}"
curl -sSfL "${URL}" | tar -xz -C "${DEST}" gitleaks
chmod +x "${DEST}/gitleaks"
echo "Installed ${DEST}/gitleaks ($("${DEST}/gitleaks" version))"
