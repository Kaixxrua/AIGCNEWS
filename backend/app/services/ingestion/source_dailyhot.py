from __future__ import annotations

"""DailyHot 聚合热榜数据源（自托管 DailyHotApi 上游，纯函数无状态）。

上游契约（imsyy/DailyHotApi 统一响应）：
    GET {base_url}/{endpoint}
    → {"code": 200, "name", "title", "type", "updateTime",
       "total", "data": [{"id", "title", "desc", "hot", "timestamp", "url", ...}]}

采集策略：
  - 逐个端点拉取热榜，每端点按 hot 降序保留 per_endpoint_limit 条；
  - hot 量级跨端点不可比（微博百万级 vs 小众站点数百），score 归一化为
    端点内名次分（榜首 100，逐名递减），raw_score 保留原始 hot；
  - 端点级失败只跳过该端点，不影响其他端点（错误聚合进返回值日志字段）。
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

import httpx

logger = logging.getLogger(__name__)

_TZ_CST = timezone(timedelta(hours=8))

SOURCE_NAME = "dailyhot"
SOURCE_CHANNEL = "dailyhot_daily"


def parse_endpoint_list(raw: str) -> list[str]:
    """解析逗号分隔的端点配置，去空白去重保序。"""
    seen: dict[str, None] = {}
    for part in raw.split(","):
        name = part.strip()
        if name and name not in seen:
            seen[name] = None
    return list(seen)


def _normalise_item(
    item: Dict[str, Any],
    *,
    endpoint: str,
    feed_title: str,
    rank: int,
) -> Dict[str, Any] | None:
    title = str(item.get("title") or "").strip()
    url = str(item.get("url") or "").strip()
    if not title or not url:
        return None

    try:
        hot = float(item.get("hot") or 0.0)
    except (TypeError, ValueError):
        hot = 0.0

    published_date = ""
    timestamp = item.get("timestamp")
    try:
        if timestamp:
            # DailyHotApi 时间戳为毫秒；个别端点给秒，按量级兼容。
            value = float(timestamp)
            seconds = value / 1000 if value > 1e12 else value
            published_date = (
                datetime.fromtimestamp(seconds, _TZ_CST).date().isoformat()
            )
    except (TypeError, ValueError, OSError, OverflowError):
        published_date = ""

    return {
        "source": SOURCE_NAME,
        "source_channel": SOURCE_CHANNEL,
        "channel": SOURCE_CHANNEL,
        "endpoint": endpoint,
        "feed_name": feed_title or endpoint,
        "title": title,
        "url": url,
        "summary": str(item.get("desc") or "").strip(),
        "raw_score": hot,
        # 端点内名次归一：让 _select_top 跨端点可比（榜首 100，逐名 -1）。
        "score": max(0.0, 100.0 - float(rank - 1)),
        "rank_in_period": rank,
        "published_date": published_date,
        "language": "zh",
    }


async def _fetch_endpoint(
    client: httpx.AsyncClient,
    *,
    base_url: str,
    endpoint: str,
    per_endpoint_limit: int,
) -> tuple[str, list[Dict[str, Any]], str | None]:
    """拉取单个端点，返回 (endpoint, items, error)；失败不抛出。"""
    try:
        response = await client.get(f"{base_url}/{endpoint}")
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        logger.warning("[DailyHot] 端点 %s 拉取失败: %s", endpoint, exc)
        return endpoint, [], str(exc)

    if payload.get("code") != 200:
        message = str(payload.get("message") or "unknown")
        logger.warning("[DailyHot] 端点 %s 返回异常: %s", endpoint, message)
        return endpoint, [], message

    feed_title = f"{payload.get('title') or ''}{payload.get('type') or ''}"
    raw_items = payload.get("data") or []

    def _hot(item: Dict[str, Any]) -> float:
        try:
            return float(item.get("hot") or 0.0)
        except (TypeError, ValueError):
            return 0.0

    ranked = sorted(raw_items, key=_hot, reverse=True)[:per_endpoint_limit]
    items = [
        normalised
        for rank, item in enumerate(ranked, start=1)
        if (normalised := _normalise_item(
            item, endpoint=endpoint, feed_title=feed_title, rank=rank
        ))
        is not None
    ]
    return endpoint, items, None


async def fetch_dailyhot_items(
    *,
    base_url: str,
    endpoints: list[str],
    per_endpoint_limit: int = 5,
    timeout_seconds: float = 8.0,
) -> List[Dict[str, Any]]:
    """聚合多个 DailyHotApi 端点的热榜条目。

    Args:
        base_url: DailyHotApi 服务地址（编排内网，如 http://dailyhot:6688）
        endpoints: 端点路由名列表（36kr / ithome / sspai / ...）
        per_endpoint_limit: 每端点保留条数（按 hot 降序）
        timeout_seconds: 单端点请求超时

    Returns:
        标准化 paper dict 列表（空列表表示全部端点失败或无数据）。
    """
    if not endpoints:
        return []

    base = base_url.rstrip("/")
    merged: list[Dict[str, Any]] = []
    async with httpx.AsyncClient(
        timeout=timeout_seconds,
        headers={"User-Agent": "AIGCNews-DailyHot/1.0"},
    ) as client:
        for endpoint in endpoints:
            _, items, _ = await _fetch_endpoint(
                client,
                base_url=base,
                endpoint=endpoint,
                per_endpoint_limit=per_endpoint_limit,
            )
            merged.extend(items)

    # 跨端点交错排序：按端点内名次优先，让各榜头部条目均匀进入 Top-N。
    merged.sort(key=lambda item: (item["rank_in_period"], item["endpoint"]))
    for index, item in enumerate(merged, start=1):
        item["rank_in_period"] = index
    logger.info(
        "[DailyHot] 聚合完成: %d 端点 → %d 条", len(endpoints), len(merged)
    )
    return merged
