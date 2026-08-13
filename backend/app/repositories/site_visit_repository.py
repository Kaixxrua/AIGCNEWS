from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol


@dataclass(frozen=True)
class SiteVisitStats:
    """站点访问计数（纯次数口径）：每次进入网站计一次，不去重。

    today_visits 为指定自然日（CST）的次数，total_visits 为全量累计。
    """

    today_visits: int
    total_visits: int


class SiteVisitRecorder(Protocol):
    def record_visit(self, day: date) -> SiteVisitStats: ...


class SiteVisitStatsReader(Protocol):
    def get_visit_stats(self, day: date) -> SiteVisitStats: ...


class SiteVisitRepository(SiteVisitRecorder, SiteVisitStatsReader, Protocol):
    """Persistence boundary for site visit day counters."""
