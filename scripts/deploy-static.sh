#!/usr/bin/env bash

set -euo pipefail

# 静态站点发布控制器位于仓库之外（私有部署工具），必须通过环境变量显式指定：
#   export DEPLOY_STATIC_CONTROLLER=/path/to/deploy.py
if [[ -z "${DEPLOY_STATIC_CONTROLLER:-}" ]]; then
  echo "错误：未设置 DEPLOY_STATIC_CONTROLLER（指向仓库外的 deploy.py 路径）。" >&2
  exit 2
fi
readonly CONTROLLER="${DEPLOY_STATIC_CONTROLLER}"

exec python3 "${CONTROLLER}" publish aigcnews "$@"
