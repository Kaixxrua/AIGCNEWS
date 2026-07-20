#!/usr/bin/env bash

set -euo pipefail

readonly CONTROLLER="${DEPLOY_STATIC_CONTROLLER:-/home/kaixxrua/deploy-static/deploy.py}"

exec python3 "${CONTROLLER}" publish aigcnews "$@"
