from __future__ import annotations

"""带来源标记的落地统计纯策略：ref 白名单、落地页归一与监控行组装。

口径说明：
- MCP（mcp-go/internal/ratelimit/projection.go）与 /api/v1（routes_projects_api.py）的
  429 文案里，升级链接带 ``?ref={mcp,api}-429-{anon,daily,monthly}``；前端 visitBeacon
  在路由接管前读出 ref 与落地路径，随访问 beacon 一起上报。
- 只收白名单里的 ref；不认识的值整条忽略（访问照常计数）。落地页只分 /mcp 与
  /membership，其余路径一律记 other，不把客户端给的任意字符串写进库。
- 值域由本模块约束，site_landing_days 表不加 CHECK（见 0083 迁移）。
"""

from typing import Iterable

from backend.app.repositories.site_visit_repository import LandingVisits

#: 429 提示链接的来源标记：{mcp,api} 区分 MCP 与 /api/v1，后缀对应文案变体
#: （anon=匿名日配额，daily=免费档每 24 小时，monthly=免费档滚动 30 天）。
LANDING_SOURCES: tuple[str, ...] = (
    "mcp-429-anon",
    "mcp-429-daily",
    "mcp-429-monthly",
    "api-429-anon",
    "api-429-daily",
    "api-429-monthly",
)

#: 429 文案里链接指向的落地页。
LANDING_PATHS: tuple[str, ...] = ("/mcp", "/membership")

#: 带了合法 ref 却落在别的路径（手改链接、站内跳转后才上报等）时的落地页取值。
OTHER_LANDING_PATH = "other"


def normalize_landing(ref: str | None, path: str | None) -> tuple[str, str] | None:
    """白名单内的 ref 返回 (来源标记, 落地页)，否则返回 None（不记落地）。"""
    source = (ref or "").strip()
    if source not in LANDING_SOURCES:
        return None
    landing_path = (path or "").strip().lower()
    if len(landing_path) > 1:
        landing_path = landing_path.rstrip("/")
    return source, landing_path if landing_path in LANDING_PATHS else OTHER_LANDING_PATH


def build_landing_rows(rows: Iterable[LandingVisits]) -> list[dict[str, object]]:
    """按落地次数降序排（同数按来源标记、落地页），监控面板直接渲染。"""
    return [
        {"source": row.source, "path": row.path, "landings": row.landings}
        for row in sorted(rows, key=lambda row: (-row.landings, row.source, row.path))
    ]
