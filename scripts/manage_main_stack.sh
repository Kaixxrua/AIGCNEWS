#!/usr/bin/env bash
set -Eeuo pipefail

readonly ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly COMPOSE_FILE="${ROOT_DIR}/docker/docker-compose.yml"
readonly APP_ENV_FILE="${ROOT_DIR}/.env"
readonly RELEASE_ENV_FILE="${AIGCNEWS_RELEASE_ENV:-${ROOT_DIR}/.release.env}"
readonly PRICEAI_ENV_FILE="${ROOT_DIR}/../.priceai-node.env"
# 私有部署 overlay（不随开源仓库发布）：存在时自动并入编排，
# 承载姊妹服务、外部编排网与私有 nginx 挂载；不存在则核心栈独立可用。
readonly PRIVATE_COMPOSE_FILE="${AIGCNEWS_PRIVATE_COMPOSE:-${ROOT_DIR}/../aigcnews_private/deploy/docker-compose.private.yml}"
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

has_private_overlay() {
  [[ -f "${PRIVATE_COMPOSE_FILE}" ]]
}

validate_inputs() {
  [[ -f "${APP_ENV_FILE}" ]] || fail "environment file not found: ${APP_ENV_FILE}"
  if has_private_overlay; then
    [[ -f "${PRICEAI_ENV_FILE}" ]] || fail "environment file not found: ${PRICEAI_ENV_FILE}"
  fi
  [[ "${COMPOSE_PROJECT_NAME:-${EXPECTED_PROJECT}}" == "${EXPECTED_PROJECT}" ]] ||
    fail "COMPOSE_PROJECT_NAME must be ${EXPECTED_PROJECT}"
}

compose() {
  local -a args=(
    --env-file "${APP_ENV_FILE}"
    --project-name "${EXPECTED_PROJECT}"
    --file "${COMPOSE_FILE}"
  )
  if [[ -f "${RELEASE_ENV_FILE}" ]]; then
    args=(
      --env-file "${APP_ENV_FILE}"
      --env-file "${RELEASE_ENV_FILE}"
      --project-name "${EXPECTED_PROJECT}"
      --file "${COMPOSE_FILE}"
    )
  fi
  if has_private_overlay; then
    args+=(
      --env-file "${PRICEAI_ENV_FILE}"
      --file "${PRIVATE_COMPOSE_FILE}"
    )
  fi
  docker compose "${args[@]}" "$@"
}

# 生产 boot 路径（存在私有 overlay 时）必须启用 dailyhot profile：
# scheduler_registry.py 注册了 dailyhot_hotlists 采集任务，需要编排内的
# DailyHotApi 上游；不显式启用时 `up --remove-orphans` 会把手动启动的
# aigc-dailyhot 当 orphan 拆除。开源核心部署无 overlay 则不强制，
# 需要 dailyhot 时自行设置 COMPOSE_PROFILES（见 docs/dailyhot-source.md）。
# 调用方已设置 COMPOSE_PROFILES 时保留其值，仅补齐 dailyhot。
ensure_dailyhot_profile() {
  has_private_overlay || return 0
  case ",${COMPOSE_PROFILES:-}," in
    *,dailyhot,*) ;;
    *) COMPOSE_PROFILES="${COMPOSE_PROFILES:+${COMPOSE_PROFILES},}dailyhot" ;;
  esac
  export COMPOSE_PROFILES
}

main() {
  require_command docker
  [[ -f "${COMPOSE_FILE}" ]] || fail "compose file not found: ${COMPOSE_FILE}"
  ensure_dailyhot_profile

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
