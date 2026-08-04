#!/usr/bin/env python3
"""按批次限定范围富化 GitHub 项目：只处理本次运行新入库的候选。

选取口径（三重去重，绝不触碰项目库存量）：
1. source_channels 含指定 --channel（本次回填的批次标记）；
2. first_seen_at >= --first-seen-after（本次运行才开始出现的行；
   存量行即使被合并了同一渠道，first_seen_at 仍保持原值，天然排除）；
3. NOT EXISTS succeeded 富化（已有成功富化的仓库一律跳过，不重复消耗 LLM）。

用法：
    python scripts/enrich_github_projects_run.py \
        --channel growth_search_2025_500_created_20250109_pushed_20250709 \
        --first-seen-after 2026-08-03T06:30:00+00:00 \
        --batch-limit 200 --concurrency 4
"""
from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.core.postgres_database import postgres_database  # noqa: E402
from backend.app.repositories.postgres_project_enrichment_repository import (  # noqa: E402
    _RUN_SCOPE_WHERE,
    PostgresGitHubProjectEnrichmentRepository,
    _github_fingerprint,
)
from backend.app.repositories.project_catalog_normalization import (  # noqa: E402
    normalize_project_row,
)
from backend.app.services.ingestion.github_project_enricher import (  # noqa: E402
    GitHubProjectEnricher,
)

MAX_CONCURRENCY = 10


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Enrich only repos newly ingested by one backfill run"
    )
    parser.add_argument("--channel", required=True, help="批次渠道标记（source_channels 包含匹配）")
    parser.add_argument("--first-seen-after", required=True, help="只处理 first_seen_at 不早于该时间的行（ISO 8601）")
    parser.add_argument("--min-stars", type=int, default=500, help="star 下限（与入库门槛一致）")
    parser.add_argument("--batch-limit", type=int, default=200, help="每批处理多少条")
    parser.add_argument("--max-total", type=int, default=0, help="本次最多富化多少条；0 表示全部")
    parser.add_argument("--concurrency", type=int, default=4, help=f"并发数（1-{MAX_CONCURRENCY}）")
    parser.add_argument("--dry-run", action="store_true", help="只统计待富化数量，不调用 LLM")
    return parser


def parse_iso(value: str) -> str:
    """校验 ISO 8601 时间并原样返回（交给 PG 做 timestamptz 比较）。"""
    try:
        datetime.fromisoformat(value)
    except ValueError:
        raise SystemExit("--first-seen-after 必须是 ISO 8601 时间，如 2026-08-03T06:30:00+00:00") from None
    return value


def count_run_candidates(
    db: Any, *, channel: str, first_seen_after: str, min_stars: int
) -> int:
    with db.transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) AS n" + _RUN_SCOPE_WHERE,
                (f"%{channel}%", first_seen_after, min_stars),
            )
            return int(cursor.fetchone()["n"])


def list_run_candidates(
    db: Any,
    *,
    channel: str,
    first_seen_after: str,
    min_stars: int,
    after_repo_id: str = "",
    limit: int,
) -> list[dict[str, Any]]:
    """按 repo_id 键集分页取批次内候选，附带富化所需的指纹与规范化字段。"""
    with db.transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT c.repo_id, c.full_name, c.title, c.url, c.description,
                       c.language, c.topics_json, c.created_at, c.pushed_at,
                       c.source_channels, c.first_seen_at, c.last_seen_at,
                       c.last_snapshot_at,
                       COALESCE(c.stars, 0) AS stars,
                       COALESCE(c.forks, 0) AS forks,
                       COALESCE(c.watchers, 0) AS watchers
                """
                + _RUN_SCOPE_WHERE
                + "  AND c.repo_id > %s ORDER BY c.repo_id LIMIT %s",
                (f"%{channel}%", first_seen_after, min_stars, after_repo_id, limit),
            )
            rows = cursor.fetchall()

    selected: list[dict[str, Any]] = []
    for source_row in rows:
        row = dict(source_row)
        row["source_fingerprint"] = _github_fingerprint(row)
        selected.append(normalize_project_row(row))
    return selected


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    channel = args.channel.strip()
    first_seen_after = parse_iso(args.first_seen_after.strip())
    if not channel:
        raise SystemExit("--channel 不能为空")
    batch_limit = max(1, min(int(args.batch_limit), 500))
    concurrency = max(1, min(int(args.concurrency), MAX_CONCURRENCY))

    repository = PostgresGitHubProjectEnrichmentRepository(postgres_database)
    pending = count_run_candidates(
        repository._database,
        channel=channel,
        first_seen_after=first_seen_after,
        min_stars=args.min_stars,
    )
    summary: dict[str, Any] = {
        "status": "dry_run" if args.dry_run else "success",
        "channel": channel,
        "first_seen_after": first_seen_after,
        "min_stars": args.min_stars,
        "pending": pending,
    }
    if args.dry_run or pending == 0:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0

    enricher = GitHubProjectEnricher(db=repository)
    target = pending if args.max_total <= 0 else min(pending, int(args.max_total))
    processed = succeeded = failed = 0
    after_repo_id = ""
    while processed < target:
        rows = list_run_candidates(
            repository._database,
            channel=channel,
            first_seen_after=first_seen_after,
            min_stars=args.min_stars,
            after_repo_id=after_repo_id,
            limit=min(batch_limit, target - processed),
        )
        if not rows:
            break
        after_repo_id = str(rows[-1]["repo_id"])
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = [executor.submit(enricher._enrich_and_store, row) for row in rows]
            for future in as_completed(futures):
                if future.result():
                    succeeded += 1
                else:
                    failed += 1
        processed += len(rows)
        print(
            f"[EnrichRun] 已处理 {processed}/{target}（成功 {succeeded}，失败 {failed}）。",
            flush=True,
        )

    summary.update({"processed": processed, "succeeded": succeeded, "failed": failed})
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
