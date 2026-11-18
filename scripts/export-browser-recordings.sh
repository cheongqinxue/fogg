#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
mapfile -t workers < <(docker ps -q --filter label=com.docker.compose.service=browser-worker)
if [[ ${#workers[@]} -ne 1 ]]; then
  echo "Start exactly one browser-worker container before exporting." >&2
  exit 1
fi
destination="${1:-$repo_root/.data/browser-recordings}"
mkdir -p "$destination"
docker cp "${workers[0]}:/recordings/." "$destination/"
echo "Recordings copied to $destination"
