# AIGC Radar MCP 测评套件

用 [mcp-eval](https://github.com/lastmile-ai/mcp-eval)（PyPI 发行名 `mcpevals`）
对本仓库自研的 AIGC Radar MCP server（生产入站实现位于 `mcp-go/`）做两层测评：

| 层 | 文件 | 内容 | LLM 消耗 |
|---|---|---|---|
| 契约层 | `test_contract.py` | 直接调用全部 8 个工具（legacy `get_project_library` 已于 e703a17 删除），断言无错误、载荷非空、关键字段在 | 无 |
| 场景层 | `test_scenarios.py` | 真实 LLM 客户端挂 MCP 跑 8 个场景，断言工具路由正确 + LLM judge 按 rubric 打分 | 每场景 2~5 次调用 |

报告输出到 `test-reports/`（json + markdown，git 忽略）。

## 运行

```bash
evals/mcp/run.sh                 # 全部
evals/mcp/run.sh test_contract.py    # 只跑契约层（快、零 LLM 成本）
evals/mcp/run.sh test_scenarios.py   # 只跑场景层
```

`run.sh` 会自动：

1. 从仓库根 `.env` 注入 `OPENAI_API_KEY` / `OPENAI_BASE_URL`（仅进程环境）；
2. 首次运行时从 `~/.claude.json` 的 `aigc-news` 配置生成
   `mcpeval.secrets.yaml`（Bearer 头，0600，git 忽略）；
3. 切到本目录再启动 pytest。

## 注意事项（踩过的坑）

- **必须从本目录运行**：`mcp_eval` 在 import 时按 CWD 读取 `.env`，
  仓库根的 `.env` 与其 pydantic 配置模型字段冲突，会直接在导入阶段崩溃。
  `run.sh` 已处理，手工跑 pytest 时务必先 `cd evals/mcp`。
- **依赖钉版 `mcp<2`**：`mcp-agent 0.2.x` 依赖官方 SDK 1.x 的
  `mcp.server.fastmcp`；`mcp 2.0` 已移除该模块。测评专用 `.venv` 中必须
  `uv pip install --python .venv/bin/python 'mcp<2'`。
- **PyPI 上的 `mcp-eval` 是占位包**（0.0.1，无代码），真身在 GitHub：
  `uv pip install 'git+https://github.com/lastmile-ai/mcp-eval.git'`，
  安装后发行名为 `mcpevals`。
- 测评默认打**本机后端** `http://127.0.0.1:8000/api/mcp`（与生产同代码同库，
  省去外网往返）；改 `mcpeval.yaml` 的 `url` 即可指向其他环境。
- 场景层串行执行（`execution.max_concurrency: 1`），避免触发 MCP 入站限流。
