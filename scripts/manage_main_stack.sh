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

# Go MCP 是核心入站服务，即使 Compose 使用 profile 隔离历史迁移路径，
# 生产 boot/reconcile 也必须始终启用 mcp-go。否则 `up --remove-orphans`
# 会拆掉已运行的 aigc-mcp-go，使公网 /api/mcp 返回 502。
# 存在私有 overlay 时还必须启用 dailyhot：调度器依赖编排内的
# DailyHotApi 上游。调用方已设置的其他 profiles 原样保留。
ensure_profile() {
  local profile="$1"
  case ",${COMPOSE_PROFILES:-}," in
    *,"${profile}",*) ;;
    *) COMPOSE_PROFILES="${COMPOSE_PROFILES:+${COMPOSE_PROFILES},}${profile}" ;;
  esac
}

ensure_required_profiles() {
  ensure_profile "mcp-go"
  if has_private_overlay; then
    ensure_profile "dailyhot"
  fi
  export COMPOSE_PROFILES
}

main() {
  require_command docker
  [[ -f "${COMPOSE_FILE}" ]] || fail "compose file not found: ${COMPOSE_FILE}"
  ensure_required_profiles

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
