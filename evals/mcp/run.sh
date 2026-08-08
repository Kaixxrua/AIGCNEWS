#!/usr/bin/env bash
# AIGC Radar MCP 测评一键入口。
# 用法:  evals/mcp/run.sh [pytest 参数...]     （可在任意目录调用）
set -euo pipefail

EVAL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$EVAL_DIR/../.." && pwd)"
PY="$ROOT/.venv/bin/python"

[ -x "$PY" ] || { echo "缺少 $PY —— 先在仓库根执行: uv venv .venv && uv pip install --python .venv/bin/python 'git+https://github.com/lastmile-ai/mcp-eval.git' 'mcp<2' pytest-asyncio"; exit 1; }

# 从仓库根 .env 注入 LLM 凭据（仅进程环境，不落盘、不回显）
set -a
# shellcheck disable=SC1090
source <(grep -E '^(OPENAI_API_KEY|OPENAI_BASE_URL)=' "$ROOT/.env")
set +a

# 中转站要求走后端同款代理出口（WireGuard 对端的 mihomo）；
# NO_PROXY 排除本机 MCP endpoint，避免被代理劫走
export HTTP_PROXY="socks5h://10.20.0.1:1080" HTTPS_PROXY="socks5h://10.20.0.1:1080"
export NO_PROXY="127.0.0.1,localhost" no_proxy="127.0.0.1,localhost"

# mcp-eval 在 import 时读取 CWD 的 .env —— 必须切到本目录，避开仓库根 .env
cd "$EVAL_DIR"

# 从 ~/.claude.json 的 aigc-news 配置生成被测 endpoint 的 Bearer 头（git 忽略）
if [ ! -f mcpeval.secrets.yaml ]; then
  "$PY" - <<'PY'
import json, os, sys
cfg = json.load(open(os.path.expanduser('~/.claude.json')))
srv = (cfg.get('mcpServers') or {}).get('aigc-news') \
   or ((cfg.get('projects') or {}).get('/home/kaixxrua/AIGCNEWS', {}).get('mcpServers') or {}).get('aigc-news')
if not srv:
    sys.exit('在 ~/.claude.json 中找不到 aigc-news MCP 配置，请手动创建 mcpeval.secrets.yaml')
auth = srv['headers']['Authorization']
with open('mcpeval.secrets.yaml', 'w') as f:
    f.write('mcp:\n  servers:\n    aigc-radar:\n      headers:\n        Authorization: "' + auth + '"\n')
os.chmod('mcpeval.secrets.yaml', 0o600)
print('已生成 mcpeval.secrets.yaml（0600，git 忽略）')
PY
fi

exec "$PY" -m pytest "$@"
