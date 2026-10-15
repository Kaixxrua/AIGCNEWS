from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol

#: 平台桶应用层枚举：beacon 按 User-Agent 归类后计入访问量的合法值域。
#: 展示顺序即元组顺序；新增桶只改这里与前端映射，不动 schema。
#: linux 桶自 2026-09-29 起从 other 拆出，此前的 Linux 访问仍留在历史 other 行里。
PLATFORM_BUCKETS: tuple[str, ...] = ("ios", "android", "windows", "macos", "linux", "other")

#: 未携带/无法识别 User-Agent 时的落桶默认值。
DEFAULT_PLATFORM = "other"

#: 爬虫、无头浏览器、脚本客户端等自动化访问的落桶值：只写平台维度表，
#: 不进 site_visit_days，因此不计入任何访问量，仅供监控面板单列展示。
AUTOMATED_PLATFORM = "bot"


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


@dataclass(frozen=True)
class LandingVisits:
    """单个（来源标记, 落地页）在窗口内的落地次数：同一访客同一天只计一次。"""

    source: str
    path: str
    landings: int


class SiteVisitRecorder(Protocol):
    def record_browser_visit(self, day: date, visitor_id: str) -> None: ...

    def record_visit(self, day: date, platform: str = DEFAULT_PLATFORM) -> SiteVisitStats: ...

    def record_automated_visit(self, day: date) -> None: ...

    def record_landing(self, day: date, source: str, path: str) -> None: ...


class SiteVisitStatsReader(Protocol):
    def get_visit_stats(self, day: date) -> SiteVisitStats: ...


class SiteVisitPlatformReader(Protocol):
    """平台维度聚合读取：since 为窗口下界（含），None 表示全量累计。"""

    def get_platform_breakdown(self, since: date | None) -> list[PlatformVisits]: ...


class SiteLandingReader(Protocol):
    """落地来源聚合读取：start、end 为窗口上下界（均含）。"""

    def get_landing_breakdown(self, start: date, end: date) -> list[LandingVisits]: ...


class SiteVisitRepository(
    SiteVisitRecorder, SiteVisitStatsReader, SiteVisitPlatformReader, SiteLandingReader, Protocol
):
    """Persistence boundary for site visit day counters (total + per-platform + landing source)."""
