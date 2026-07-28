#!/usr/bin/env bash
set -Eeuo pipefail

readonly ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly COMPOSE_FILE="${ROOT_DIR}/docker/docker-compose.project-catalog-rehearsal.yml"
readonly EXPECTED_PROJECT="aigcnews-project-catalog-rehearsal"
readonly REQUIRED_CONFIRMATION="REHEARSE_PROJECT_CATALOG_CUTOVER"

usage() {
  cat <<'USAGE'
Usage: scripts/rehearse_project_catalog_cutover.sh <config|up|recreate|status|logs|down>

config    Validate the isolated rehearsal configuration without printing secrets.
up        Start the self-contained rehearsal topology.
recreate  Recreate the backend after a validated mode transition.
status    Show rehearsal service status.
logs      Follow all rehearsal service logs.
down      Stop rehearsal services, preserving MySQL and PostgreSQL data.

Set REHEARSAL_CONFIRM=REHEARSE_PROJECT_CATALOG_CUTOVER for mutating actions.
Use docker compose down -v manually only when explicitly authorized to delete data.
USAGE
}

fail() {
  printf 'error: %s\n' "$*" >&2
  exit 2
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || fail "required command not found: $1"
}

require_env() {
  local name="$1"
  [[ -n "${!name:-}" ]] || fail "${name} must be set"
}

validate_bool() {
  local name="$1"
  local value="${!name}"
  [[ "${value}" == "true" || "${value}" == "false" ]] ||
    fail "${name} must be true or false"
}

validate_mode() {
  REHEARSAL_CATALOG_BACKEND="${REHEARSAL_CATALOG_BACKEND:-mysql}"
  REHEARSAL_CATALOG_CAPTURE="${REHEARSAL_CATALOG_CAPTURE:-true}"
  REHEARSAL_CATALOG_SYNC="${REHEARSAL_CATALOG_SYNC:-false}"
  REHEARSAL_CATALOG_SHADOW="${REHEARSAL_CATALOG_SHADOW:-false}"
  REHEARSAL_SEARCH_STRATEGY="${REHEARSAL_SEARCH_STRATEGY:-legacy}"
  export REHEARSAL_CATALOG_BACKEND REHEARSAL_CATALOG_CAPTURE
  export REHEARSAL_CATALOG_SYNC REHEARSAL_CATALOG_SHADOW REHEARSAL_SEARCH_STRATEGY

  [[ "${REHEARSAL_CATALOG_BACKEND}" == "mysql" || "${REHEARSAL_CATALOG_BACKEND}" == "postgres" ]] ||
    fail "REHEARSAL_CATALOG_BACKEND must be mysql or postgres"
  validate_bool REHEARSAL_CATALOG_CAPTURE
  validate_bool REHEARSAL_CATALOG_SYNC
  validate_bool REHEARSAL_CATALOG_SHADOW
  [[ "${REHEARSAL_SEARCH_STRATEGY}" == "legacy" || "${REHEARSAL_SEARCH_STRATEGY}" == "shadow" || "${REHEARSAL_SEARCH_STRATEGY}" == "v2" ]] ||
    fail "REHEARSAL_SEARCH_STRATEGY must be legacy, shadow, or v2"

  [[ "${REHEARSAL_CATALOG_CAPTURE}" == "true" ]] ||
    fail "rehearsal requires REHEARSAL_CATALOG_CAPTURE=true"
  if [[ "${REHEARSAL_CATALOG_BACKEND}" == "postgres" ]]; then
    [[ "${REHEARSAL_CATALOG_SYNC}" == "true" ]] ||
      fail "postgres mode requires REHEARSAL_CATALOG_SYNC=true"
    [[ "${REHEARSAL_CATALOG_SHADOW}" == "false" ]] ||
      fail "postgres mode requires REHEARSAL_CATALOG_SHADOW=false"
  fi
  if [[ "${REHEARSAL_CATALOG_SHADOW}" == "true" ]]; then
    [[ "${REHEARSAL_CATALOG_BACKEND}" == "mysql" ]] ||
      fail "catalog shadow mode requires the mysql catalog backend"
    [[ "${REHEARSAL_CATALOG_SYNC}" == "true" ]] ||
      fail "catalog shadow mode requires REHEARSAL_CATALOG_SYNC=true"
  fi
}

validate_inputs() {
  require_env REHEARSAL_BACKEND_IMAGE
  require_env REHEARSAL_RELEASE_ID
  require_env REHEARSAL_ENV_FILE
  require_env REHEARSAL_MYSQL_ROOT_PASSWORD
  require_env REHEARSAL_MYSQL_DATABASE
  require_env REHEARSAL_MYSQL_USER
  require_env REHEARSAL_MYSQL_PASSWORD
  require_env REHEARSAL_POSTGRES_DATABASE
  require_env REHEARSAL_POSTGRES_USER
  require_env REHEARSAL_POSTGRES_PASSWORD
  require_env REHEARSAL_MINIO_ROOT_USER
  require_env REHEARSAL_MINIO_ROOT_PASSWORD

  [[ "${REHEARSAL_BACKEND_IMAGE}" == *@sha256:* ]] ||
    fail "REHEARSAL_BACKEND_IMAGE must be pinned by digest (@sha256:...)"
  [[ "${REHEARSAL_ENV_FILE}" == /* ]] ||
    fail "REHEARSAL_ENV_FILE must be an absolute path"
  [[ -f "${REHEARSAL_ENV_FILE}" ]] ||
    fail "REHEARSAL_ENV_FILE does not exist"
  [[ "${COMPOSE_PROJECT_NAME:-${EXPECTED_PROJECT}}" == "${EXPECTED_PROJECT}" ]] ||
    fail "COMPOSE_PROJECT_NAME must be ${EXPECTED_PROJECT}"
  validate_mode
}

confirm_mutation() {
  [[ "${REHEARSAL_CONFIRM:-}" == "${REQUIRED_CONFIRMATION}" ]] ||
    fail "set REHEARSAL_CONFIRM=${REQUIRED_CONFIRMATION} for this action"
}

compose() {
  docker compose --project-name "${EXPECTED_PROJECT}" --file "${COMPOSE_FILE}" "$@"
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
      printf 'rehearsal compose configuration is valid\n'
      ;;
    up)
      validate_inputs
      confirm_mutation
      compose config --quiet
      compose up --detach --no-build --pull never --wait
      ;;
    recreate)
      validate_inputs
      confirm_mutation
      compose config --quiet
      compose up --detach --no-build --pull never --wait --no-deps --force-recreate project-catalog-backend
      ;;
    status)
      compose ps
      ;;
    logs)
      compose logs --follow
      ;;
    down)
      confirm_mutation
      compose down --remove-orphans
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
