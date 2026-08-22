from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol

#: 平台桶应用层枚举：beacon 按 User-Agent 归类后的唯一合法值域。
#: 展示顺序即元组顺序；新增桶只改这里与前端映射，不动 schema。
PLATFORM_BUCKETS: tuple[str, ...] = ("ios", "android", "windows", "macos", "other")

#: 未携带/无法识别 User-Agent 时的落桶默认值。
DEFAULT_PLATFORM = "other"


@dataclass(frozen=True)
class SiteVisitStats:
    """站点访问计数（纯次数口径）：每次进入网站计一次，不去重。

    today_visits 为指定自然日（CST）的次数，total_visits 为全量累计。
    """

    today_visits: int
    total_visits: int


@dataclass(frozen=True)
class PlatformVisits:
    """单个平台桶在窗口内的访问次数（纯次数口径，与 SiteVisitStats 一致）。"""

    platform: str
    visits: int


class SiteVisitRecorder(Protocol):
    def record_visit(self, day: date, platform: str = DEFAULT_PLATFORM) -> SiteVisitStats: ...


class SiteVisitStatsReader(Protocol):
    def get_visit_stats(self, day: date) -> SiteVisitStats: ...


class SiteVisitPlatformReader(Protocol):
    """平台维度聚合读取：since 为窗口下界（含），None 表示全量累计。"""

    def get_platform_breakdown(self, since: date | None) -> list[PlatformVisits]: ...


class SiteVisitRepository(SiteVisitRecorder, SiteVisitStatsReader, SiteVisitPlatformReader, Protocol):
    """Persistence boundary for site visit day counters (total + per-platform)."""
