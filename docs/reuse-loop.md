# 复用检查闭环：触发 → 检索 → 回执 → 度量

> 产品定位的一句话落地：**在做项目的时候，AI 能自动发现成熟的技术，避免再重复造轮子。**
> 本文档描述这条闭环的四个环节、各触发面的安装配方，以及度量口径。

## 闭环总览

```text
用户提出实现类需求
  → ① 触发（确定性注入复用检查提醒）
  → ② 检索（AIGC Radar 项目库：500 Stars 准入 + 双语精选）
  → ③ 回执（agent 汇报决策：adopted / reference_only / declined）
  → ④ 度量（复用率聚合：adopted / 全部决策）
```

没有①，"记得先查"靠模型自觉，不稳定；没有③④，无法回答"复用检查到底有没有用"。
四环齐了，定位才成立。

## ① 触发层（三个面，按需选用）

### a) dsh 插件（dsh-aigc-radar）

dsh 原生插件在 `agent/pre-step` 事件上注册了瀑布监听器：用户输入经
意图正则（实现/开发/搭建/implement/build/...）× 规模正则（系统/服务/引擎/system/service/engine/...）
双重门控后，在该 step 注入一条 `pluginUserMessage`，引导 agent 先调用
`search_ai_projects` 再动手。只在每个 turn 的 step 1 触发，不改写用户原文。

仓库：[dsh-aigc-radar](https://github.com/Kaixxrua/dsh-aigc-radar)（随 awesome-dsh-plugin 投稿公开发布）。

### b) Claude Code UserPromptSubmit hook（本机配方）

Claude Code 用户在 `~/.claude/settings.json` 的 `hooks` 中登记（**合并，不覆盖既有 hooks**）：

```json
"hooks": {
  "UserPromptSubmit": [
    {
      "matcher": "",
      "hooks": [
        {
          "type": "command",
          "command": "python3 /home/kaixxrua/.claude/hooks/aigc_radar_reuse_check.py",
          "timeout": 5
        }
      ]
    }
  ]
}
```

脚本放在 `~/.claude/hooks/aigc_radar_reuse_check.py`，行为契约：

- 同样的意图×规模双正则门（zh+en），prompt 最短 8 字符；
- 命中后向 stdout 输出 `hookSpecificOutput.additionalContext`——复用检查指引 +
  本地库实时 top-3 候选（`GET 127.0.0.1:8000/api/projects?q=关键词`，单请求 1.2s
  超时，最多两次关键词尝试）；
- **每个 session 只注入一次**（状态文件 `~/.claude/hooks/.aigc-radar-reuse-state.json`，
  7 天 GC）；任何异常都静默 exit 0，永不阻断 prompt；
- 关键词抽取：拉丁词（≥3 字符，RAG/SDK/OAuth 这类术语命中率最高）优先，
  中文按停用词切碎取残余段——后端检索是单串 ILIKE，整句中文必然不命中；
- `AIGC_RADAR_API_BASE` 环境变量可覆盖 API 地址（默认 `http://127.0.0.1:8000`）。

<details>
<summary>完整脚本（与线上部署版本一致）</summary>

```python
#!/usr/bin/env python3
"""AIGC Radar 复用检查 hook（Claude Code UserPromptSubmit）。"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

API_BASE = os.environ.get("AIGC_RADAR_API_BASE", "http://127.0.0.1:8000")
STATE_PATH = os.path.expanduser("~/.claude/hooks/.aigc-radar-reuse-state.json")
STATE_TTL_SECONDS = 7 * 24 * 3600
MIN_PROMPT_CHARS = 8
REQUEST_TIMEOUT = 1.2

INTENT_PATTERN = re.compile(
    r"(实现|开发|搭建|写一|写个|构建|做个|做一|新建|从零|撸一|手写"
    r"|implement|build|create|develop|scaffold|write\s+a|set\s+up|from\s+scratch)",
    re.IGNORECASE,
)
SCALE_PATTERN = re.compile(
    r"(系统|服务|平台|模块|引擎|框架|管线|流水线|中间件|网关|调度|看板|面板"
    r"|完整|全栈|整套|后端|前端|微服务|插件"
    r"|system|service|platform|module|engine|framework|pipeline|middleware"
    r"|gateway|scheduler|dashboard|panel|backend|frontend|microservice|plugin"
    r"|full[- ]?stack|complete)",
    re.IGNORECASE,
)
TOKEN_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9_+.-]{2,}|[一-鿿]{2,}")
CJK_STOPWORDS = (
    "帮我", "我想", "我要", "需要", "请", "一个", "一下", "完整的", "的",
    "实现", "开发", "搭建", "构建", "支持", "基于", "使用", "可以", "能够",
)


def load_state() -> dict[str, float]:
    try:
        with open(STATE_PATH, encoding="utf-8") as handle:
            data = json.load(handle)
        return {str(k): float(v) for k, v in data.items()}
    except Exception:
        return {}


def save_session(session_id: str) -> None:
    try:
        now = time.time()
        state = {k: ts for k, ts in load_state().items() if now - ts < STATE_TTL_SECONDS}
        state[session_id] = now
        os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
        with open(STATE_PATH, "w", encoding="utf-8") as handle:
            json.dump(state, handle)
    except Exception:
        pass


def extract_keywords(prompt: str) -> list[str]:
    latin: list[str] = []
    cjk: list[str] = []
    for token in TOKEN_PATTERN.findall(prompt):
        if re.fullmatch(r"[一-鿿]+", token):
            for stopword in CJK_STOPWORDS:
                token = token.replace(stopword, " ")
            cjk.extend(part for part in token.split() if len(part) >= 2)
        else:
            latin.append(token)
    latin.sort(key=len, reverse=True)
    cjk.sort(key=len, reverse=True)
    ordered: list[str] = []
    seen: set[str] = set()
    for token in [*latin, *cjk]:
        lowered = token.lower()
        if lowered not in seen:
            seen.add(lowered)
            ordered.append(token)
    return ordered[:2]


def fetch_candidates(keywords: list[str]) -> list[dict]:
    for keyword in keywords:
        query = urllib.parse.urlencode({"q": keyword[:60], "page_size": 3})
        try:
            with urllib.request.urlopen(
                f"{API_BASE}/api/projects?{query}", timeout=REQUEST_TIMEOUT
            ) as response:
                payload = json.load(response)
        except Exception:
            continue
        items = payload.get("items") or []
        if items:
            return items[:3]
    return []


def render_candidate(item: dict) -> str:
    name = item.get("full_name") or item.get("title") or "?"
    stars = item.get("stars")
    stars_text = f" ★{stars}" if isinstance(stars, int) else ""
    description = (item.get("description") or "").strip().split("\n")[0][:60]
    return f"  - {name}{stars_text} — {description}" if description else f"  - {name}{stars_text}"


def build_context(prompt: str) -> str:
    lines = [
        "【AIGC Radar 复用检查】检测到实现类需求。动手前先查成熟方案，避免重复造轮子：",
        "1. 搜索：优先调用 MCP 工具 search_github_ai_projects（AI/Agent/RAG/LLM 方向）"
        "或 search_github_projects（通用软件）；无 MCP 时可查本地库"
        f" GET {API_BASE}/api/projects?q=关键词",
        "2. 评估每个命中：直接集成（adopted）/ 仅参考设计（reference_only）/ 确认自研（declined）",
        "3. 决策落定后回执一次：MCP 工具 submit_project_adoption，"
        "或 POST /api/projects/adoptions（project_full_name/decision/reason/query）",
    ]
    candidates = fetch_candidates(extract_keywords(prompt))
    if candidates:
        lines.append("库内实时候选（供参考，需自行核实星数与维护状态）：")
        lines.extend(render_candidate(item) for item in candidates)
    else:
        lines.append("（本地库本次未命中或不可达，仍建议显式检索后再动手）")
    return "\n".join(lines)


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return
    prompt = str(payload.get("prompt") or "").strip()
    if len(prompt) < MIN_PROMPT_CHARS:
        return
    if not (INTENT_PATTERN.search(prompt) and SCALE_PATTERN.search(prompt)):
        return
    session_id = str(payload.get("session_id") or "")
    if session_id and session_id in load_state():
        return
    context = build_context(prompt)
    if session_id:
        save_session(session_id)
    json.dump(
        {
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": context,
            }
        },
        sys.stdout,
        ensure_ascii=False,
    )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
```

</details>

### c) MCP 协议层软引导（默认开启）

`initialize` 响应的 `instructions` 与工具描述里写明：任何项目检索导致具体复用决策后，
调用一次 `submit_project_adoption`。这是零安装面——所有连上 AIGC Radar MCP 的
客户端自动获得。

## ② 检索层

| 通道 | 入口 |
|---|---|
| MCP（推荐） | `search_github_ai_projects`（AI/Agent/RAG/LLM 工程产物）/ `search_github_projects`（通用软件） |
| 程序化 REST | `GET /api/v1/projects/search`（+ `/api/v1/projects/categories`） |
| 网站浏览（免费） | `GET /api/projects?q=...&page_size=...` |

同一项目库：500 Stars 准入、分类体系、中英双语描述与标签、星标增长快照。

程序化通道（MCP 与 `/api/v1`）共享同一套限速与收费口径：MCP token 即
API key（`Authorization: Bearer`，McpConnect 页签发）；匿名按 IP 每个固定
24 小时窗口 10 次，Free 为每 24 小时 20 次 + 滚动 30 天 400 次，
VIP 为每 24 小时 400 次 + 滚动 30 天 8,000 次，**两通道共用一个配额池**；超限返回 429 +
`Retry-After` + 分档升级引导。网站浏览端点不参与配额，永远免费。

## ③ 回执层

决策三态语义：

| decision | 含义 | 典型后续动作 |
|---|---|---|
| `adopted` | 直接集成——引入依赖、部署或 fork 使用 | 写依赖清单、配置、集成代码 |
| `reference_only` | 仅参考设计——读其实现，自己写 | 引用架构/算法，不引入依赖 |
| `declined` | 确认自研——库内无合适方案或不满足约束 | 动手造轮子（这是合法结果，不是失败） |

两个等价入口（字段一致，均有界且仅追加）：

- **MCP**：`submit_project_adoption(project_full_name, decision, reason?, query?)`；
  响应 `structuredContent` 含 `receipt`、`stats` 与 `attribution`。
- **REST**：`POST /api/projects/adoptions`，body：
  `{"project_full_name": "owner/repo", "decision": "adopted", "reason": "...", "query": "..."}`；
  响应 `{"receipt": {...}, "stats": {...}}`。

约束：每个项目每个决策最多回执一次；仅"被列入/被比较"不构成决策，不要回执。

## ④ 度量层

`GET /api/projects/adoptions/stats?days=30`（days ∈ [1, 365]）：

```json
{
  "window_days": 30,
  "window": {"adopted": 12, "reference_only": 5, "declined": 3},
  "total": {"adopted": 40, "reference_only": 21, "declined": 9},
  "window_adoption_rate": 0.6,
  "total_adoption_rate": 0.5714
}
```

复用率口径：`adoption_rate = adopted / 全部决策`（保留 4 位小数，无数据时为 0.0）。
`reference_only` 与 `declined` 都计入分母——前者是"避免重复造轮子"的弱成功，
后者是闭环正常运转的证据（检索后仍选择自研，说明检查发生了）。

## 数据模型（迁移 0046）

```sql
project_adoptions (
    id BIGSERIAL PRIMARY KEY,
    project_full_name TEXT NOT NULL,   -- 不加 FK：回执可指向 fallback/未入库项目
    decision TEXT NOT NULL,            -- 应用层 Literal 校验，无 DB CHECK（0045 先例）
    reason TEXT NOT NULL DEFAULT '',
    query TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT 'mcp', -- mcp / rest / plugin / hook
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
-- 索引：project_full_name、created_at
```

## 部署状态

- 代码与迁移已合入 main（回执闭环 `ec9418d`，本文档 `0ce2841`）。
- 迁移在后端启动时应用。本机后端已热载新代码（回执路由已注册），但 0046
  尚未应用——当前访问回执端点返回 500（表不存在），重启即得。0042 重启
  封锁已于 2026-08-17 解除；刻意不在并行会话存在未提交 backend WIP 时
  主动重启。
- 公网 aigcnews.cn 端点随下一次部署生效；自托管部署重启即得。
