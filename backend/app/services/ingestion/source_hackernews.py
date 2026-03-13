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
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

# HN 官方 Firebase API
_HN_TOP_STORIES_URL = "https://hacker-news.firebaseio.com/v0/topstories.json"
_HN_ITEM_URL = "https://hacker-news.firebaseio.com/v0/item/{item_id}.json"

# 取首页前 30 条
_TOP_N = 30

# 24 小时时间窗口
_MAX_AGE_HOURS = 24

# 并发控制（Firebase API 较宽松，可全量并发）
_SEMAPHORE_LIMIT = 30


async def _fetch_item_async(
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
    item_id: int,
) -> Optional[Dict[str, Any]]:
    """异步拉取单个 HN story 详情。"""
    async with semaphore:
        try:
            resp = await client.get(
                _HN_ITEM_URL.format(item_id=item_id),
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            if (
                data
                and data.get("type") == "story"
                and not data.get("dead")
                and not data.get("deleted")
            ):
                return data
            return None
        except Exception as exc:
            logger.debug("[HackerNews] 拉取 item %d 失败: %s", item_id, exc)
            return None


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

    # Step 1: 获取 topstories ID 列表（前 30）
    try:
        async with httpx.AsyncClient(
            timeout=15, trust_env=True, follow_redirects=True
        ) as client:
            resp = await client.get(_HN_TOP_STORIES_URL)
            resp.raise_for_status()
            all_ids = resp.json()
    except Exception as exc:
        logger.error("[HackerNews] 获取 topstories 失败: %s", exc)
        return []

    if not all_ids or not isinstance(all_ids, list):
        logger.error("[HackerNews] topstories 返回数据异常: %s", type(all_ids))
        return []

    top_ids = all_ids[:_TOP_N]
    logger.info("[HackerNews] 获取 topstories 前 %d 个 ID", len(top_ids))

    # Step 2: asyncio.gather 并发拉取每个 story 详情
    semaphore = asyncio.Semaphore(_SEMAPHORE_LIMIT)
    async with httpx.AsyncClient(
        timeout=10, trust_env=True, follow_redirects=True
    ) as client:
        tasks = [_fetch_item_async(client, semaphore, item_id) for item_id in top_ids]
        raw_results = await asyncio.gather(*tasks)

    stories: List[Dict[str, Any]] = [r for r in raw_results if r is not None]

    logger.info(
        "[HackerNews] 成功拉取 %d / %d 条 story 详情（async 并发）",
        len(stories),
        len(top_ids),
    )

    # Step 3: 24 小时时间过滤
    cutoff_ts = now_ts - (_MAX_AGE_HOURS * 3600)
    filtered: List[Dict[str, Any]] = []
    for story in stories:
        story_time = story.get("time", 0)
        if story_time >= cutoff_ts:
            filtered.append(story)
        else:
            logger.debug(
                "[HackerNews] 排除超24h帖子: id=%s title='%s' age=%.1fh",
                story.get("id"),
                (story.get("title") or "")[:50],
                (now_ts - story_time) / 3600,
            )

    logger.info(
        "[HackerNews] 24h 过滤: %d → %d 条（排除 %d 条超时帖子）",
        len(stories),
        len(filtered),
        len(stories) - len(filtered),
    )

    # Step 4: 按 score (Points) 严格降序排列
    filtered.sort(key=lambda x: int(x.get("score", 0)), reverse=True)

    # Step 5: 截取 limit 条，构造标准化输出，赋予 rank_in_period
    results: List[Dict[str, Any]] = []
    for rank, story in enumerate(filtered[:limit], start=1):
        hn_id = str(story.get("id", ""))
        url = story.get("url") or f"https://news.ycombinator.com/item?id={hn_id}"
        points = int(story.get("score", 0))
        comments = int(story.get("descendants", 0))
        story_time = story.get("time", 0)

        # published_date 使用 story 的发布时间（UTC）
        published_date = ""
        if story_time:
            try:
                published_date = datetime.fromtimestamp(
                    story_time, tz=timezone.utc
                ).strftime("%Y-%m-%d")
            except Exception:
                pass

        results.append(
            {
                "title": story.get("title", ""),
                "url": url,
                "abstract": story.get("title", ""),
                "summary": story.get("title", ""),
                "source": "hackernews",
                "source_channel": source_channel,
                "channel": source_channel,
                "score": float(points),
                "raw_score": float(points),
                "votes": points,
                "comments": comments,
                "published_date": published_date,
                "hn_id": hn_id,
                "author": story.get("by", ""),
                "rank_in_period": rank,
                "tags": ["hackernews", "daily", "top30"],
            }
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
