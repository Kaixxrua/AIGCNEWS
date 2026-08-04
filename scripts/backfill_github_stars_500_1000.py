#!/usr/bin/env python3
"""GitHub 项目库历史回填：把 stars 处于 [min-stars, max-stars] 区间的仓库
批量补录进 github_repo_candidates。

硬门槛：低于 --min-stars（默认 500）的仓库一律不入库——即使 API 返回了
也会在写入前丢弃。GitHub Search API 单查询最多返回 1000 条结果，因此按
created 日期区间递归二分，直到每个分片的结果数低于安全上限。

本脚本是 backend.app.services.ingestion.github_search_crawl 的薄封装；
运维页 GitHubProjectCrawlAdminService 复用同一引擎。

用法：
    python scripts/backfill_github_stars_500_1000.py --dry-run --limit 200
    python scripts/backfill_github_stars_500_1000.py --limit 5000
    # 对齐 growth_search 口径（新+火+活跃）：stars 不封顶、固定 created/pushed 截止
    python scripts/backfill_github_stars_500_1000.py \
        --min-stars 500 --max-stars 0 \
        --created-start 2025-01-10 --pushed-after 2025-07-09 \
        --channel growth_search_2025_500_created_20250109_pushed_20250709
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.core.postgres_database import postgres_database  # noqa: E402
from backend.app.repositories.postgres_project_ingestion_repository import (  # noqa: E402
    PostgresGitHubProjectIngestionRepository,
)
from backend.app.services.ingestion.github_search_crawl import (  # noqa: E402,F401
    SHARD_COUNT_CAP,
    SearchClient,
    _stars_query,
    crawl_github_search,
    daterange_shards,
    eligible,
    merge_channels,
    parse_search_item,
)

DEFAULT_CHANNEL = "backfill_stars_500_999"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Backfill GitHub repos in a stars band into the project library"
    )
    parser.add_argument("--min-stars", type=int, default=500, help="入库 star 下限（硬门槛，低于此值一律跳过）")
    parser.add_argument("--max-stars", type=int, default=999, help="回填 star 上限；0 表示不封顶")
    parser.add_argument("--limit", type=int, default=5000, help="最多写入多少条候选")
    parser.add_argument("--created-start", default="2008-01-01", help="created 分片起点 YYYY-MM-DD")
    parser.add_argument("--created-end", default="", help="created 分片终点 YYYY-MM-DD（默认今天）")
    parser.add_argument("--pushed-after", default="", help="只收录最后 push 晚于该日期的仓库 YYYY-MM-DD（默认不限）")
    parser.add_argument("--channel", default=DEFAULT_CHANNEL, help="写入 source_channels 的渠道标记")
    parser.add_argument("--per-shard-cap", type=int, default=SHARD_COUNT_CAP, help="单分片结果数安全上限")
    parser.add_argument("--request-interval", type=float, default=0.0, help="请求间隔秒数（默认按 token 有无自适应）")
    parser.add_argument("--dry-run", action="store_true", help="只抓取统计，不写数据库")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.min_stars < 0 or (args.max_stars and args.max_stars < args.min_stars):
        raise SystemExit("--max-stars 必须 >= --min-stars >= 0（0 表示不封顶）")
    created_start = date.fromisoformat(args.created_start)
    created_end = date.fromisoformat(args.created_end) if args.created_end else date.today()
    if created_end < created_start:
        raise SystemExit("--created-end 必须不早于 --created-start")
    pushed_after = args.pushed_after.strip()
    if pushed_after:
        try:
            date.fromisoformat(pushed_after)
        except ValueError:
            raise SystemExit("--pushed-after 必须是 YYYY-MM-DD") from None
    channel = args.channel.strip() or DEFAULT_CHANNEL

    summary = crawl_github_search(
        min_stars=args.min_stars,
        max_stars=args.max_stars,
        limit=args.limit,
        created_start=created_start,
        created_end=created_end,
        pushed_after=pushed_after,
        channel=channel,
        per_shard_cap=args.per_shard_cap,
        request_interval=args.request_interval,
        dry_run=args.dry_run,
        ingestion=None
        if args.dry_run
        else PostgresGitHubProjectIngestionRepository(postgres_database),
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
