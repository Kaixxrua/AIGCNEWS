#!/usr/bin/env python3
"""GitHub 项目库历史回填：把 stars 处于 [min-stars, max-stars] 区间的仓库
批量补录进 github_repo_candidates。

硬门槛：低于 --min-stars（默认 500）的仓库一律不入库——即使 API 返回了
也会在写入前丢弃。GitHub Search API 单查询最多返回 1000 条结果，因此按
created 日期区间递归二分，直到每个分片的结果数低于安全上限。

用法：
    python scripts/backfill_github_stars_500_1000.py --dry-run --limit 200
    python scripts/backfill_github_stars_500_1000.py --limit 5000
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402

from backend.app.core.config import settings  # noqa: E402
from backend.app.core.postgres_database import postgres_database  # noqa: E402
from backend.app.repositories.postgres_project_ingestion_repository import (  # noqa: E402
    PostgresGitHubProjectIngestionRepository,
)

GITHUB_API_BASE = "https://api.github.com"
# 单分片结果数安全上限（API 硬上限 1000，留 10% 余量防边界抖动丢数据）
SHARD_COUNT_CAP = 900
DEFAULT_CHANNEL = "backfill_stars_500_999"
REQUEST_TIMEOUT = 30


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Backfill GitHub repos in a stars band into the project library"
    )
    parser.add_argument("--min-stars", type=int, default=500, help="入库 star 下限（硬门槛，低于此值一律跳过）")
    parser.add_argument("--max-stars", type=int, default=999, help="回填 star 上限")
    parser.add_argument("--limit", type=int, default=5000, help="最多写入多少条候选")
    parser.add_argument("--created-start", default="2008-01-01", help="created 分片起点 YYYY-MM-DD")
    parser.add_argument("--created-end", default="", help="created 分片终点 YYYY-MM-DD（默认今天）")
    parser.add_argument("--per-shard-cap", type=int, default=SHARD_COUNT_CAP, help="单分片结果数安全上限")
    parser.add_argument("--request-interval", type=float, default=0.0, help="请求间隔秒数（默认按 token 有无自适应）")
    parser.add_argument("--dry-run", action="store_true", help="只抓取统计，不写数据库")
    return parser


def _token() -> str:
    return (settings.github_token or os.getenv("GITHUB_TOKEN", "")).strip()


def _headers(use_token: bool) -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "RAG-AIGC-Agent/1.0",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = _token()
    if use_token and token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _stars_query(min_stars: int, max_stars: int, start: date, end: date) -> str:
    return f"stars:{min_stars}..{max_stars} created:{start.isoformat()}..{end.isoformat()}"


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

    def __init__(self, *, interval: float) -> None:
        self._client = httpx.Client(timeout=REQUEST_TIMEOUT, trust_env=True)
        self._use_token = bool(_token())
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
                headers=_headers(self._use_token),
                params=params,
            )
            if response.status_code == 401 and self._use_token:
                self._use_token = False
                continue
            if response.status_code in (403, 429):
                retry_after = int(response.headers.get("Retry-After", "0") or 0)
                wait = max(retry_after, 30 * (attempt + 1))
                print(f"[Backfill] 限流 {response.status_code}，等待 {wait}s 后重试...", flush=True)
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


def load_existing_channels(db: Any, repo_ids: list[str]) -> dict[str, str]:
    if not repo_ids:
        return {}
    with db.transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT repo_id, COALESCE(source_channels, '') AS channels "
                "FROM github_repo_candidates WHERE repo_id = ANY(%s)",
                (repo_ids,),
            )
            return {row["repo_id"]: row["channels"] for row in cursor.fetchall()}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.min_stars < 0 or args.max_stars < args.min_stars:
        raise SystemExit("--max-stars 必须 >= --min-stars >= 0")
    created_start = date.fromisoformat(args.created_start)
    created_end = date.fromisoformat(args.created_end) if args.created_end else date.today()
    if created_end < created_start:
        raise SystemExit("--created-end 必须不早于 --created-start")

    client = SearchClient(interval=args.request_interval)
    summary: dict[str, Any] = {
        "status": "dry_run" if args.dry_run else "success",
        "min_stars": args.min_stars,
        "max_stars": args.max_stars,
        "limit": args.limit,
    }
    try:
        shards = daterange_shards(
            created_start,
            created_end,
            lambda s, e: client.total_count(
                _stars_query(args.min_stars, args.max_stars, s, e)
            ),
            cap=args.per_shard_cap,
        )
        shard_counts = {
            f"{s.isoformat()}..{e.isoformat()}": total for s, e, total in shards
        }
        summary["shards"] = shard_counts
        summary["total_available"] = sum(shard_counts.values())
        print(f"[Backfill] 分片 {len(shards)} 个，可回填总量 {summary['total_available']}。", flush=True)

        ingestion = None if args.dry_run else PostgresGitHubProjectIngestionRepository(postgres_database)
        seen: set[str] = set()
        fetched = upserted = skipped_low_stars = skipped_duplicates = 0
        stop = False
        for start, end, available in shards:
            if stop:
                break
            query = _stars_query(args.min_stars, args.max_stars, start, end)
            pages = min(10, (min(available, args.limit - upserted) + 99) // 100)
            for page in range(1, pages + 1):
                if upserted >= args.limit:
                    stop = True
                    break
                items = client.search(query, per_page=100, page=page).get("items") or []
                if not items:
                    break
                batch: list[dict[str, Any]] = []
                for item in items:
                    payload = parse_search_item(item)
                    if payload is None:
                        continue
                    fetched += 1
                    if not eligible(payload, min_stars=args.min_stars):
                        skipped_low_stars += 1
                        continue
                    key = payload["full_name"].lower()
                    if key in seen:
                        skipped_duplicates += 1
                        continue
                    seen.add(key)
                    batch.append(payload)
                    if upserted + len(batch) >= args.limit:
                        break
                if batch and ingestion is not None:
                    channels = load_existing_channels(
                        ingestion._database, [p["repo_id"] for p in batch]
                    )
                    for payload in batch:
                        payload["source_channels"] = merge_channels(
                            channels.get(payload["repo_id"], ""), DEFAULT_CHANNEL
                        )
                        ingestion.upsert_github_repo_candidate(payload)
                upserted += len(batch)
                print(
                    f"[Backfill] {start}..{end} 第 {page} 页：本批 {len(batch)}，累计写入 {upserted}/{args.limit}。",
                    flush=True,
                )

        summary.update(
            {
                "fetched": fetched,
                "upserted": upserted,
                "skipped_low_stars": skipped_low_stars,
                "skipped_duplicates": skipped_duplicates,
                "api_requests": client.requests,
            }
        )
    finally:
        client.close()
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
