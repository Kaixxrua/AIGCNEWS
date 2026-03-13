from __future__ import annotations

"""爬虫抽象基类与标准化结果容器。

所有数据源爬虫必须继承 BaseCrawler 并实现 fetch() 方法。
BaseCrawler 提供统一的接口约定和异常隔离保证。

设计原则：
  - source_*.py 是底层数据获取库（纯函数，无副作用）
  - crawlers/*.py 是带标准接口的爬虫包装器（处理异常、计算 snapshot_date、标准化输出）
  - pipeline.py 是轻量编排器（调度爬虫 → 内容丰富 → 三库写入）
"""

import logging
import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import List, Optional

logger = logging.getLogger(__name__)

# UTC+8 时区
_TZ_CST = timezone(timedelta(hours=8))


def today_cst() -> str:
    """返回 CST（UTC+8）当天日期字符串 YYYY-MM-DD。"""
    return datetime.now(_TZ_CST).date().isoformat()


@dataclass
class CrawlResult:
    """单次爬虫采集的标准化结果。

    Attributes:
        source: 数据源标识符（arxiv / github / news / producthunt / hackernews）
        source_channel: 具体渠道（如 huggingface_daily_html / github_trending_weekly）
        snapshot_date: 业务归属日期 YYYY-MM-DD（决定写入哪天的快照）
        period: 采集周期（daily / weekly / monthly）
        items: 标准化的 paper/repo/article dict 列表
        error: 错误信息（None=成功，非 None=该次采集失败但不影响其他源）
    """

    source: str
    source_channel: str
    snapshot_date: str
    period: str
    items: List[dict] = field(default_factory=list)
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        """采集是否成功。"""
        return self.error is None

    @property
    def count(self) -> int:
        """采集到的条目数量。"""
        return len(self.items)

    def __repr__(self) -> str:
        status = f"{self.count} items" if self.ok else f"ERROR: {self.error}"
        return (
            f"CrawlResult(source={self.source!r}, channel={self.source_channel!r}, "
            f"date={self.snapshot_date!r}, period={self.period!r}, {status})"
        )


class BaseCrawler(ABC):
    """所有数据源爬虫的统一抽象基类。

    子类必须实现：
      - source_name: 数据源标识符
      - supported_periods: 支持的周期列表
      - fetch(): 执行单周期采集

    保证：
      - fetch() 内部的任何异常都会被捕获，返回 CrawlResult(error=str)
      - 不会抛出异常到调用方，确保一个源的失败不影响其他源
    """

    @property
    @abstractmethod
    def source_name(self) -> str:
        """数据源标识符，如 'arxiv' / 'github' / 'news'。"""

    @property
    @abstractmethod
    def supported_periods(self) -> List[str]:
        """支持的采集周期列表，如 ['daily', 'weekly', 'monthly']。"""

    @abstractmethod
    async def _do_fetch(
        self,
        period: str,
        limit: int,
        target_date: Optional[str] = None,
    ) -> CrawlResult:
        """实际采集逻辑（子类实现）。

        允许抛出异常，BaseCrawler.fetch() 会自动捕获。

        Args:
            period: 采集周期（daily / weekly / monthly）
            limit: 最多返回条数
            target_date: 业务归属日期（YYYY-MM-DD），None 时由子类决定默认值

        Returns:
            CrawlResult 实例
        """

    async def fetch(
        self,
        period: str,
        limit: int = 25,
        target_date: Optional[str] = None,
    ) -> CrawlResult:
        """执行单周期采集（异常安全）。

        自动捕获 [`BaseCrawler._do_fetch()`](backend/app/services/ingestion/base_crawler.py:93)
        内的任何异常，返回 error [`CrawlResult`](backend/app/services/ingestion/base_crawler.py:32)。
        """
        snapshot_date = target_date or today_cst()
        try:
            result = await self._do_fetch(
                period=period,
                limit=limit,
                target_date=target_date,
            )
            logger.info(
                "[%s] %s 榜采集完成: %d 条 (snapshot=%s)",
                self.source_name,
                period,
                result.count,
                result.snapshot_date,
            )
            return result
        except Exception as exc:
            logger.error(
                "[%s] %s 榜采集异常: %s",
                self.source_name,
                period,
                exc,
                exc_info=True,
            )
            return CrawlResult(
                source=self.source_name,
                source_channel=f"{self.source_name}_{period}_error",
                snapshot_date=snapshot_date,
                period=period,
                items=[],
                error=str(exc),
            )

    async def fetch_all_periods(
        self,
        limit: int = 25,
        top_n: int = 10,
        target_date: Optional[str] = None,
    ) -> List[CrawlResult]:
        """采集所有支持的周期，返回结果列表。

        每个周期独立执行，一个周期失败不影响其他周期。
        使用 [`asyncio.gather()`](backend/app/services/ingestion/base_crawler.py:15)
        并发调度所有周期。
        """
        tasks = [
            self.fetch(period=period, limit=limit, target_date=target_date)
            for period in self.supported_periods
        ]
        results = await asyncio.gather(*tasks)
        for result in results:
            if result.ok and result.count > top_n:
                original_count = result.count
                result.items.sort(
                    key=lambda p: float(p.get("raw_score") or p.get("score") or 0),
                    reverse=True,
                )
                result.items = result.items[:top_n]
                logger.info(
                    "[%s] %s 榜 Top-%d 筛选完成（原 %d 条）",
                    self.source_name,
                    result.period,
                    len(result.items),
                    original_count,
                )
        return results
