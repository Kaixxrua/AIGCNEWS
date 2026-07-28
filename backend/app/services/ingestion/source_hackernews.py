from __future__ import annotations

"""Hacker News 数据源采集（async 极速版 — 通过官方 Firebase API）

采集逻辑（v3 async 重构）：
  1. 通过 HN 官方 Firebase API 获取 topstories 前 30 个 ID
  2. **asyncio.gather 并发** 拉取每个 story 的详情（title, url, score, time 等）
  3. 过滤掉发布时间距当前超过 24 小时的帖子
  4. 按 score (Points) 严格降序排列
  5. 重新赋予 rank_in_period (1, 2, 3...)

性能优化（v3）：
  - 使用 httpx.AsyncClient + asyncio.gather 替代 ThreadPoolExecutor
  - 30 个并发协程同时拉取，无线程切换开销
  - 总耗时从数秒压缩到百毫秒级别

不再使用 Algolia Search API，不再做 AI/ML 关键词过滤（取首页真实热榜）。

source_channel 值：hn_daily_html
"""

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional

from backend.app.services.ingestion.sources import hackernews_policy
from backend.app.services.ingestion.sources.hackernews_transport import (
    HackerNewsTransport,
    httpx,
)

logger = logging.getLogger(__name__)

_HN_TOP_STORIES_URL = "https://hacker-news.firebaseio.com/v0/topstories.json"
_HN_ITEM_URL = "https://hacker-news.firebaseio.com/v0/item/{item_id}.json"
_TOP_N = 30
_MAX_AGE_HOURS = 24
_SEMAPHORE_LIMIT = 30


async def fetch_hackernews_items_async(
    limit: int = 30,
    period: str = "daily",
    target_date: Optional[str] = None,
    use_llm_filter: bool = False,
) -> List[Dict[str, Any]]:
    """异步版：从 HN Firebase API 采集首页 Top-30 故事。

    使用 asyncio.gather 并发 30 个请求，无线程切换开销。

    Args:
        limit: 最多返回条数（默认 30）
        period: 周期参数（兼容接口，实际固定 daily）
        target_date: 兼容参数（未使用）
        use_llm_filter: 兼容参数（未使用）

    Returns:
        包含 title/url/score/rank_in_period 等字段的 dict 列表，
        严格按 score 降序排列，rank_in_period 从 1 开始递增。
    """
    source_channel = "hn_daily_html"
    now_ts = time.time()

    adapter = HackerNewsTransport()
    try:
        top_ids = await adapter.fetch_top_ids()
    except Exception as exc:
        logger.error("[HackerNews] 获取 topstories 失败: %s", exc)
        return []
    if not top_ids:
        logger.error("[HackerNews] topstories 返回数据异常: %s", list)
        return []
    logger.info("[HackerNews] 获取 topstories 前 %d 个 ID", len(top_ids))

    raw_results = await adapter.fetch_items(top_ids)
    stories = [
        story
        for story in raw_results
        if hackernews_policy.is_story(story)
    ]
    logger.info(
        "[HackerNews] 成功拉取 %d / %d 条 story 详情（async 并发）",
        len(stories),
        len(top_ids),
    )

    filtered = hackernews_policy.filter_recent_stories(stories, now_ts=now_ts)
    logger.info(
        "[HackerNews] 24h 过滤: %d → %d 条（排除 %d 条超时帖子）",
        len(stories),
        len(filtered),
        len(stories) - len(filtered),
    )
    ordered = hackernews_policy.sort_by_score(filtered)
    results = hackernews_policy.project_stories(
        ordered,
        limit=limit,
        source_channel=source_channel,
    )

    logger.info(
        "[HackerNews] 最终返回 %d 条（Top score: %s, Min score: %s）",
        len(results),
        results[0].get("raw_score") if results else "N/A",
        results[-1].get("raw_score") if results else "N/A",
    )
    return results


# ── 同步兼容包装器（供 crawlers 调用） ────────────────────────────────────────


def fetch_hackernews_items(
    limit: int = 30,
    period: str = "daily",
    target_date: Optional[str] = None,
    use_llm_filter: bool = False,
) -> List[Dict[str, Any]]:
    """同步包装器：自动检测事件循环，选择合适的调用方式。"""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(
                asyncio.run,
                fetch_hackernews_items_async(
                    limit=limit,
                    period=period,
                    target_date=target_date,
                    use_llm_filter=use_llm_filter,
                ),
            )
            return future.result(timeout=60)
    else:
        return asyncio.run(
            fetch_hackernews_items_async(
                limit=limit,
                period=period,
                target_date=target_date,
                use_llm_filter=use_llm_filter,
            )
        )
