from __future__ import annotations

"""站点访问的平台维度纯策略：User-Agent 归类 + 窗口聚合响应组装。

口径说明：
- 归类只取 UA 小写子串，不引入 UA 解析依赖；顺序即语义，调整顺序必须同步测试。
- iOS 必须先于 macOS：iPhone/iPad 的 UA 带 `like Mac OS X` 字样，顺序颠倒会把
  iOS 流量错划进 macos。
- iPadOS 13+ 桌面模式 UA 伪装成 `Macintosh; Intel Mac OS X 10_15`，纯 UA 无法
  区分，计入 macos（面板文案已向用户注明该限制）。
- windows phone 落入 windows 桶（份额可忽略）；空 UA、Linux、爬虫一律 other。
- 平台桶值域由本模块与 site_visit_repository.PLATFORM_BUCKETS 约束，DB 无 CHECK。
"""

from datetime import date, timedelta
from typing import Iterable, TypedDict

from backend.app.repositories.site_visit_repository import (
    DEFAULT_PLATFORM,
    PLATFORM_BUCKETS,
    PlatformVisits,
)

#: 读端点合法窗口枚举（Query pattern 与之保持一致）：today/7d/30d 为含今天的自然日数。
VISIT_STATS_WINDOWS: tuple[str, ...] = ("today", "7d", "30d", "all")

_WINDOW_DAY_SPAN: dict[str, int] = {"today": 1, "7d": 7, "30d": 30}


def classify_platform(user_agent: str | None) -> str:
    """把 User-Agent 归入平台桶；空/无法识别一律 other。"""
    if not user_agent:
        return DEFAULT_PLATFORM
    ua = user_agent.casefold()
    if "iphone" in ua or "ipad" in ua or "ipod" in ua:
        return "ios"
    if "android" in ua:
        return "android"
    if "windows" in ua:
        return "windows"
    if "mac os x" in ua or "macintosh" in ua:
        return "macos"
    return DEFAULT_PLATFORM


def window_start_date(window: str, today: date) -> date | None:
    """窗口下界（含）：today→当天；7d/30d→today-(N-1)；all→None（无下界）。"""
    span = _WINDOW_DAY_SPAN.get(window)
    if span is None:
        return None
    return today - timedelta(days=span - 1)


class PlatformShareEntry(TypedDict):
    platform: str
    visits: int
    share: float


class PlatformBreakdownResponse(TypedDict):
    window: str
    start_date: str | None
    end_date: str
    total_visits: int
    platforms: list[PlatformShareEntry]


def build_platform_breakdown_response(
    rows: Iterable[PlatformVisits],
    window: str,
    today: date,
) -> PlatformBreakdownResponse:
    """把仓储聚合行组装为读端点响应：固定桶序、补零值桶、share 一位小数。

    未识别桶（历史脏数据等）折叠进 other，保证响应桶集合恒为 PLATFORM_BUCKETS。
    share 仅为信息性字段：一位小数直接相加可能漂移 ±0.1，前端展示百分比以原始
    visits 本地大余数法重算为准。
    """
    visits_by_bucket = dict.fromkeys(PLATFORM_BUCKETS, 0)
    for row in rows:
        bucket = row.platform if row.platform in visits_by_bucket else DEFAULT_PLATFORM
        visits_by_bucket[bucket] += max(int(row.visits), 0)

    total = sum(visits_by_bucket.values())
    start = window_start_date(window, today)
    return {
        "window": window,
        "start_date": start.isoformat() if start else None,
        "end_date": today.isoformat(),
        "total_visits": total,
        "platforms": [
            {
                "platform": bucket,
                "visits": visits,
                "share": round(visits * 100.0 / total, 1) if total else 0.0,
            }
            for bucket, visits in visits_by_bucket.items()
        ],
    }
