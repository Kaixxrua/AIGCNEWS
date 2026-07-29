#!/usr/bin/env bash
set -Eeuo pipefail

readonly ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly COMPOSE_FILE="${ROOT_DIR}/docker/docker-compose.yml"
readonly APP_ENV_FILE="${ROOT_DIR}/.env"
readonly PRICEAI_ENV_FILE="${ROOT_DIR}/../.priceai-node.env"
readonly EXPECTED_PROJECT="docker"

usage() {
  cat <<'USAGE'
Usage: scripts/manage_main_stack.sh <config|up|status|logs>

config  Validate the main Compose configuration without printing secrets.
up      Reconcile the complete stack and wait for healthy services.
status  Show main stack service status.
logs    Follow main stack logs.
USAGE
}

fail() {
  printf 'error: %s\n' "$*" >&2
  exit 2
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || fail "required command not found: $1"
}

validate_inputs() {
  [[ -f "${APP_ENV_FILE}" ]] || fail "environment file not found: ${APP_ENV_FILE}"
  [[ -f "${PRICEAI_ENV_FILE}" ]] || fail "environment file not found: ${PRICEAI_ENV_FILE}"
  [[ "${COMPOSE_PROJECT_NAME:-${EXPECTED_PROJECT}}" == "${EXPECTED_PROJECT}" ]] ||
    fail "COMPOSE_PROJECT_NAME must be ${EXPECTED_PROJECT}"
}

compose() {
  docker compose \
    --env-file "${APP_ENV_FILE}" \
    --env-file "${PRICEAI_ENV_FILE}" \
    --project-name "${EXPECTED_PROJECT}" \
    --file "${COMPOSE_FILE}" \
    "$@"
}

main() {
  require_command docker
  [[ -f "${COMPOSE_FILE}" ]] || fail "compose file not found: ${COMPOSE_FILE}"

  local action="${1:-}"
  [[ $# -eq 1 ]] || { usage >&2; exit 2; }
  case "${action}" in
    config)
      validate_inputs
      compose config --quiet
      printf 'main stack compose configuration is valid\n'
      ;;
    up)
      validate_inputs
      compose config --quiet
      compose up --detach --remove-orphans --no-build --pull never --wait --wait-timeout 300
      ;;
    status)
      validate_inputs
      compose ps
      ;;
    logs)
      validate_inputs
      compose logs --follow
      ;;
    -h|--help|help)
      usage
      ;;
    *)
      usage >&2
      exit 2
      ;;
  esac
}

main "$@"
