"""GitHub Search 爬取引擎：按 stars/created/pushed 条件分片抓取并写入候选库。

硬门槛：低于 min_stars 的仓库一律不入库——即使 API 返回了也会在写入前丢弃。
GitHub Search API 单查询最多返回 1000 条结果，因此按 created 日期区间递归二分，
直到每个分片的结果数低于安全上限。

CLI 脚本 scripts/backfill_github_stars_500_1000.py 是本模块的薄封装；
运维页 GitHubProjectCrawlAdminService 通过 crawl_github_search() 复用同一引擎。
"""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import date, timedelta
from typing import Any, Callable

import httpx

from backend.app.core.config import settings
from backend.app.repositories.project_write_repository import (
    GitHubProjectIngestionRepository,
)

logger = logging.getLogger(__name__)

GITHUB_API_BASE = "https://api.github.com"
# 单分片结果数安全上限（API 硬上限 1000，留 10% 余量防边界抖动丢数据）
SHARD_COUNT_CAP = 900
REQUEST_TIMEOUT = 30
DEFAULT_LIMIT = 5000
MAX_LIMIT = 20000


def _token(explicit: str = "") -> str:
    return (explicit or settings.github_token or os.getenv("GITHUB_TOKEN", "")).strip()


def _headers(use_token: bool, *, token: str = "") -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "RAG-AIGC-Agent/1.0",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    resolved = _token(token)
    if use_token and resolved:
        headers["Authorization"] = f"Bearer {resolved}"
    return headers


def _stars_query(
    min_stars: int,
    max_stars: int,
    start: date,
    end: date,
    *,
    pushed_after: str = "",
) -> str:
    stars = f"stars:{min_stars}..{max_stars}" if max_stars else f"stars:>={min_stars}"
    query = f"{stars} created:{start.isoformat()}..{end.isoformat()}"
    if pushed_after:
        query += f" pushed:>{pushed_after}"
    return query


def daterange_shards(
    start: date,
    end: date,
    count_for: Callable[[date, date], int],
    *,
    cap: int = SHARD_COUNT_CAP,
) -> list[tuple[date, date, int]]:
    """把 [start, end] 递归二分，直到每个子区间的结果数 <= cap。

    count_for(start, end) 返回该 created 区间的搜索结果总数；
    返回 (start, end, total) 三元组，调用方无需重复计数。
    """
    if start > end:
        return []
    total = count_for(start, end)
    if total <= cap or start == end:
        return [(start, end, total)]
    mid = start + (end - start) // 2
    return daterange_shards(start, mid, count_for, cap=cap) + daterange_shards(
        mid + timedelta(days=1), end, count_for, cap=cap
    )


def parse_search_item(item: dict[str, Any]) -> dict[str, Any] | None:
    """把 Search API item 映射为 candidates upsert 载荷；无 full_name 返回 None。"""
    full_name = str(item.get("full_name") or "").strip()
    if not full_name:
        return None
    topics = item.get("topics") if isinstance(item.get("topics"), list) else []
    return {
        "repo_id": full_name,
        "full_name": full_name,
        "title": full_name,
        "url": str(item.get("html_url") or f"https://github.com/{full_name}"),
        "description": str(item.get("description") or ""),
        "language": str(item.get("language") or ""),
        "topics_json": json.dumps([str(t) for t in topics[:10]], ensure_ascii=False),
        "created_at": str(item.get("created_at") or ""),
        "pushed_at": str(item.get("pushed_at") or ""),
        "stars": int(item.get("stargazers_count") or 0),
        "forks": int(item.get("forks_count") or 0),
        "watchers": int(item.get("watchers_count") or 0),
        "community_metrics_complete": True,
    }


def eligible(payload: dict[str, Any], *, min_stars: int) -> bool:
    """入库硬门槛：低于 min_stars 一律丢弃。"""
    return int(payload.get("stars") or 0) >= min_stars


def merge_channels(existing: str, new_channel: str) -> str:
    channels = [part.strip() for part in (existing or "").split(",") if part.strip()]
    if new_channel and new_channel not in channels:
        channels.append(new_channel)
    return ",".join(channels)


class SearchClient:
    """带限速与限流重试的 GitHub Search 客户端。"""

    def __init__(self, *, interval: float, token: str = "") -> None:
        self._client = httpx.Client(timeout=REQUEST_TIMEOUT, trust_env=True)
        self._token = token
        self._use_token = bool(_token(token))
        self._interval = interval or (2.1 if self._use_token else 6.5)
        self.requests = 0

    def close(self) -> None:
        self._client.close()

    def search(self, query: str, *, per_page: int = 100, page: int = 1) -> dict[str, Any]:
        params = {
            "q": query,
            "sort": "stars",
            "order": "desc",
            "per_page": max(1, min(per_page, 100)),
            "page": page,
        }
        for attempt in range(3):
            time.sleep(self._interval)
            self.requests += 1
            response = self._client.get(
                f"{GITHUB_API_BASE}/search/repositories",
                headers=_headers(self._use_token, token=self._token),
                params=params,
            )
            if response.status_code == 401 and self._use_token:
                self._use_token = False
                continue
            if response.status_code in (403, 429):
                retry_after = int(response.headers.get("Retry-After", "0") or 0)
                wait = max(retry_after, 30 * (attempt + 1))
                logger.info(
                    "[GitHubSearchCrawl] 限流 %s，等待 %ss 后重试...",
                    response.status_code,
                    wait,
                )
                time.sleep(wait)
                continue
            if response.status_code == 422:
                # 查询本身不被接受（如区间为空），视为无结果
                return {"total_count": 0, "items": []}
            response.raise_for_status()
            return response.json()
        raise RuntimeError(f"search failed after retries: {query}")

    def total_count(self, query: str) -> int:
        payload = self.search(query, per_page=1)
        return int(payload.get("total_count") or 0)


def validate_crawl_window(
    *,
    min_stars: int,
    max_stars: int,
    created_start: date,
    created_end: date,
    pushed_after: str = "",
) -> None:
    """跨字段校验，非法输入抛 ValueError（路由层映射为 400）。"""
    if min_stars < 0 or (max_stars and max_stars < min_stars):
        raise ValueError("max_stars 必须 >= min_stars >= 0（0 表示不封顶）")
    if created_end < created_start:
        raise ValueError("created_end 必须不早于 created_start")
    if pushed_after:
        try:
            date.fromisoformat(pushed_after)
        except ValueError:
            raise ValueError("pushed_after 必须是 YYYY-MM-DD") from None


def crawl_github_search(
    *,
    min_stars: int,
    max_stars: int,
    limit: int,
    created_start: date,
    created_end: date,
    pushed_after: str = "",
    channel: str,
    per_shard_cap: int = SHARD_COUNT_CAP,
    request_interval: float = 0.0,
    dry_run: bool = False,
    ingestion: GitHubProjectIngestionRepository | None = None,
    token: str = "",
    client: SearchClient | None = None,
) -> dict[str, Any]:
    """按条件分片爬取 GitHub 仓库并写入候选库，返回运行摘要。

    dry_run 只做分片计数（不翻页、不写库）；正式运行时 ingestion 必填，
    每批先查既有 source_channels 合并本次 channel 标记后 upsert。
    """
    pushed_after = (pushed_after or "").strip()
    channel = (channel or "").strip()
    if not channel:
        raise ValueError("channel 不能为空")
    validate_crawl_window(
        min_stars=min_stars,
        max_stars=max_stars,
        created_start=created_start,
        created_end=created_end,
        pushed_after=pushed_after,
    )
    limit = max(1, min(int(limit or DEFAULT_LIMIT), MAX_LIMIT))
    if not dry_run and ingestion is None:
        raise ValueError("正式爬取必须提供 ingestion 仓储")

    own_client = client is None
    search_client = client or SearchClient(interval=request_interval, token=token)
    summary: dict[str, Any] = {
        "status": "dry_run" if dry_run else "success",
        "min_stars": min_stars,
        "max_stars": max_stars,
        "pushed_after": pushed_after,
        "channel": channel,
        "limit": limit,
    }
    try:
        shards = daterange_shards(
            created_start,
            created_end,
            lambda s, e: search_client.total_count(
                _stars_query(min_stars, max_stars, s, e, pushed_after=pushed_after)
            ),
            cap=per_shard_cap,
        )
        shard_counts = {f"{s.isoformat()}..{e.isoformat()}": total for s, e, total in shards}
        summary["shards"] = shard_counts
        summary["total_available"] = sum(shard_counts.values())
        logger.info(
            "[GitHubSearchCrawl] 分片 %d 个，可回填总量 %d。",
            len(shards),
            summary["total_available"],
        )
        if dry_run:
            summary["api_requests"] = search_client.requests
            return summary

        seen: set[str] = set()
        fetched = upserted = skipped_low_stars = skipped_duplicates = new_candidates = 0
        stop = False
        for start, end, available in shards:
            if stop:
                break
            query = _stars_query(min_stars, max_stars, start, end, pushed_after=pushed_after)
            pages = min(10, (min(available, limit - upserted) + 99) // 100)
            for page in range(1, pages + 1):
                if upserted >= limit:
                    stop = True
                    break
                items = search_client.search(query, per_page=100, page=page).get("items") or []
                if not items:
                    break
                batch: list[dict[str, Any]] = []
                for item in items:
                    payload = parse_search_item(item)
                    if payload is None:
                        continue
                    fetched += 1
                    if not eligible(payload, min_stars=min_stars):
                        skipped_low_stars += 1
                        continue
                    key = payload["full_name"].lower()
                    if key in seen:
                        skipped_duplicates += 1
                        continue
                    seen.add(key)
                    batch.append(payload)
                    if upserted + len(batch) >= limit:
                        break
                if batch and ingestion is not None:
                    channels = ingestion.get_github_repo_source_channels(
                        [p["repo_id"] for p in batch]
                    )
                    for payload in batch:
                        if payload["repo_id"] not in channels:
                            new_candidates += 1
                        payload["source_channels"] = merge_channels(
                            channels.get(payload["repo_id"], ""), channel
                        )
                        ingestion.upsert_github_repo_candidate(payload)
                upserted += len(batch)
                logger.info(
                    "[GitHubSearchCrawl] %s..%s 第 %d 页：本批 %d，累计写入 %d/%d。",
                    start,
                    end,
                    page,
                    len(batch),
                    upserted,
                    limit,
                )

        summary.update(
            {
                "fetched": fetched,
                "upserted": upserted,
                "new_candidates": new_candidates,
                "existing_candidates_updated": upserted - new_candidates,
                "skipped_low_stars": skipped_low_stars,
                "skipped_duplicates": skipped_duplicates,
                "api_requests": search_client.requests,
            }
        )
    finally:
        if own_client:
            search_client.close()
    return summary
