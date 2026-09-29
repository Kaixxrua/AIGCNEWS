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
Usage: scripts/manage_main_stack.sh <config|migrate|up|status|logs>

config  Validate the main Compose configuration without printing secrets.
migrate Apply candidate-image PostgreSQL migrations without starting services.
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

# 后端容器以非 root（uid 1000/app）运行并 bind-mount 这些宿主目录。若目录
# 缺失，docker 会在 up/run 时以 root 代建，导致容器内 app 无法写入
# （典型：arxiv PDF 落盘 [Errno 13] Permission denied storage/papers）。
# compose 各挂载注释即要求"首次部署前宿主机预建并属主 1000"；此处把该口径
# 固化为幂等的自动步骤——由部署用户（uid 与容器 app 一致）预建，docker 便
# 不会再以 root 代建。清单须与 docker-compose.yml 的 ../storage 绑定源一致。
readonly STORAGE_BIND_DIRS=(
  "storage/papers"
  "storage/site"
  "storage/chat_uploads"
  "storage/metrics"
  "storage/x_media"
  "storage/hf_cache/huggingface"
)

# 预建 storage 绑定源目录（幂等，由部署用户拥有）。仅创建、不改属主：脚本以
# 非特权部署用户运行，对既有 root 属主目录 chown 会失败并被 set -e 掀翻部署。
# 对既有但当前用户不可写的目录只发告警、不阻断——纠正历史 root 属主是一次性
# 特权操作，交由运维执行（见告警中的 chown 提示）。
ensure_storage_dirs() {
  local rel dir
  for rel in "${STORAGE_BIND_DIRS[@]}"; do
    dir="${ROOT_DIR}/${rel}"
    mkdir -p "${dir}"
    if [[ ! -w "${dir}" ]]; then
      printf 'warning: storage 目录不可被部署用户(uid %s)写入: %s\n' "$(id -u)" "${dir}" >&2
      printf '         如为历史 root 属主，需一次性特权纠正: chown -R %s:%s %s\n' \
        "$(id -u)" "$(id -g)" "${dir}" >&2
    fi
  done
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
    migrate)
      validate_inputs
      ensure_storage_dirs
      compose config --quiet
      # Never use the running backend (which still belongs to the old release).
      # run publishes no service ports; --no-deps keeps existing services intact.
      compose run --rm --no-deps --pull never --entrypoint python backend-api -c '
from backend.app.core.postgres_database import postgres_database
from backend.app.core.postgres_migrations import PostgresMigrationRunner
import sys
try:
    runner = PostgresMigrationRunner()
    applied = runner.apply()
    if any(not item.applied for item in runner.status()):
        raise RuntimeError("pending migrations remain")
    print("PostgreSQL migration gate passed; applied:", len(applied))
except Exception:
    print("PostgreSQL migration gate failed; inspect database logs", file=sys.stderr)
    sys.exit(1)
finally:
    postgres_database.close()
'
      ;;
    up)
      validate_inputs
      ensure_storage_dirs
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

# 直接执行时运行 main；被 source（契约测试）时仅加载函数，不触发编排。
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  main "$@"
fi
