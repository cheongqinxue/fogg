#!/usr/bin/env bash
# Start Docker Compose with a named profile (subset of services).
#
# Usage:
#   ./scripts/compose-up.sh <profile> [docker compose up options...]
#   ./scripts/compose-up.sh --list-profiles
#
# Add profiles in compose_profile_services() below.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

compose_profile_services() {
  # Return a space-separated service list for docker compose up.
  case "$1" in
    full)
      # Master and isolated browser research stack run in Docker.
      printf '%s' 'ollama redis postgres phoenix agent browser-research browser-worker browser-proxy'
      ;;
    debug-agent)
      # Master runs on host; browser research remains private except loopback API.
      printf '%s' 'ollama redis postgres phoenix browser-research browser-worker browser-proxy'
      ;;
    *)
      return 1
      ;;
  esac
}

compose_list_profiles() {
  # Keep in sync with case arms in compose_profile_services().
  cat <<'EOF'
Profiles:
  full         All Compose services (agent in Docker).
  debug-agent  Compose research/browser services; run scripts/run-agent-debug.sh on the host.

Usage:
  ./scripts/compose-up.sh <profile> [--build] [-d] ...
  ./scripts/compose-up.sh --list-profiles
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  compose_list_profiles
  exit 0
fi

if [[ "${1:-}" == "--list-profiles" ]]; then
  compose_list_profiles
  exit 0
fi

PROFILE="${1:?profile required; use --list-profiles}"
shift

SERVICES="$(compose_profile_services "$PROFILE")" || {
  echo "Unknown profile: $PROFILE" >&2
  echo >&2
  compose_list_profiles >&2
  exit 2
}

read -r -a SVC <<<"$SERVICES"
COMPOSE_FILES=()
if [[ "$PROFILE" == "debug-agent" ]]; then
  COMPOSE_FILES=(-f docker-compose.yml -f deploy/docker-compose.debug-agent.yml)
fi
echo "Profile: $PROFILE → docker compose ${COMPOSE_FILES[*]} up $* ${SVC[*]}" >&2
exec docker compose "${COMPOSE_FILES[@]}" up "$@" "${SVC[@]}"
