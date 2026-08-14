#!/usr/bin/env python3
"""GitHub 项目身份巡检：改名归一化 + 确认下架不可用仓库（僵尸项目清理）。

对 github_repo_candidates 做全量活性探测（键集分页、可断点续跑）：

- 已改名（GitHub 301 / GraphQL 权威名不一致）→ 经 record_github_metric_outcomes
  携带 renamed_from，由仓储层把旧名候选行就地改名或与既有新名行合并删除，
  历史快照/日指标/榜单/画像/别名全部随迁——项目卡片直接变成改名后的项目。
- GraphQL 查无 + REST 404 → 先记一次不可用观测，随后脚本再独立探测一次
  凑满两次观测（2-strike fail-closed），availability_status 置 not_found，
  读取侧（项目库/热榜/MCP）即刻隐藏。

写入路径与日刷完全同源（record_github_metric_outcomes +
upsert_github_repo_metric_observations），本脚本只负责分页、限流避让与
404 二次确认，不含任何独立写库 SQL。

用法：
    python scripts/canonicalize_github_project_identities.py --dry-run --limit 200
    python scripts/canonicalize_github_project_identities.py            # 全量
    python scripts/canonicalize_github_project_identities.py \
        --start-after "m" --chunk 500 --interval 1.0
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.repositories.postgres_project_ingestion_repository import (  # noqa: E402
    PostgresGitHubProjectIngestionRepository,
)
from backend.app.services.ingestion.github_project_metrics_service import (  # noqa: E402
    current_github_metric_date,
    record_github_metric_outcomes,
)
from backend.app.services.ingestion.source_github import (  # noqa: E402
    fetch_github_repo_metrics,
    fetch_github_repo_metrics_batch,
)

logger = logging.getLogger("canonicalize_github_project_identities")


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Sweep all GitHub project identities: rename-normalize + confirm-hide dead repos"
    )
    parser.add_argument("--chunk", type=int, default=500, help="每批巡检的候选行数（键集分页）")
    parser.add_argument("--start-after", default="", help="从此 full_name 之后续跑（键集游标）")
    parser.add_argument("--limit", type=int, default=0, help="最多巡检多少行；0 表示全量")
    parser.add_argument("--interval", type=float, default=0.5, help="批次间隔秒数（默认 0.5）")
    parser.add_argument("--retry-sleep", type=float, default=60.0, help="批次结果缺失时重试前的等待秒数")
    parser.add_argument("--no-confirm", action="store_true", help="跳过 404 二次独立确认（默认开启）")
    parser.add_argument("--dry-run", action="store_true", help="只探测统计，不写数据库")
    return parser


def _classify(outcomes) -> dict[str, int]:
    tally = {"succeeded": 0, "renamed": 0, "not_found": 0, "unknown": 0}
    for outcome in outcomes:
        if outcome.status == "not_found":
            tally["not_found"] += 1
        elif outcome.status != "succeeded" or not outcome.metrics:
            tally["unknown"] += 1
        else:
            tally["succeeded"] += 1
            api_name = str(outcome.metrics.get("full_name") or "").strip()
            if api_name and api_name != str(outcome.full_name or "").strip():
                tally["renamed"] += 1
    return tally


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    repository = PostgresGitHubProjectIngestionRepository()
    snapshot_date = current_github_metric_date()

    totals: dict[str, int] = {
        "rows": 0,
        "fetched": 0,
        "renamed": 0,
        "not_found_observations": 0,
        "confirmed_not_found": 0,
        "newly_not_found": 0,
        "recovered": 0,
        "unknown": 0,
        "snapshots": 0,
        "missing_results": 0,
    }
    after = args.start_after.strip()
    processed = 0
    batch_no = 0

    while True:
        rows = repository.list_github_identity_sweep_targets(
            after_full_name=after, limit=args.chunk
        )
        if not rows:
            break
        after = str(rows[-1]["full_name"])
        batch_no += 1
        names = [str(row.get("full_name") or "").strip() for row in rows]
        names = [name for name in names if name]

        outcomes = fetch_github_repo_metrics_batch(names)
        got = {str(o.full_name or "").lower() for o in outcomes}
        missing = [name for name in names if name.lower() not in got]
        if missing:
            # 限流/网络中断会让批次尾部缺失；睡一轮补抓一次，仍缺则留给下次运行
            logger.warning(
                "批次 %d：%d 个仓库无抓取结果，%.0fs 后补抓一次",
                batch_no, len(missing), args.retry_sleep,
            )
            time.sleep(max(args.retry_sleep, 1.0))
            outcomes.extend(fetch_github_repo_metrics_batch(missing))
            got = {str(o.full_name or "").lower() for o in outcomes}
            still_missing = [name for name in missing if name.lower() not in got]
            if still_missing:
                totals["missing_results"] += len(still_missing)
                logger.warning(
                    "批次 %d：仍有 %d 个仓库无结果（下次运行补）：%s",
                    batch_no, len(still_missing), still_missing[:5],
                )

        if args.dry_run:
            tally = _classify(outcomes)
            for key, value in tally.items():
                mapped = {"succeeded": "fetched", "not_found": "not_found_observations"}.get(key, key)
                totals[mapped] += value
            totals["rows"] += len(rows)
            processed += len(rows)
            logger.info("批次 %d（dry-run）：%s", batch_no, tally)
        else:
            captured_at = _utcnow()
            counts = record_github_metric_outcomes(
                targets=rows,
                outcomes=outcomes,
                snapshot_date=snapshot_date,
                captured_at=captured_at,
                db=repository,
            )
            for key in (
                "fetched", "renamed", "not_found_observations",
                "newly_not_found", "recovered", "unknown", "snapshots",
            ):
                totals[key] += int(counts.get(key) or 0)
            totals["rows"] += len(rows)
            processed += len(rows)

            if not args.no_confirm:
                # 404 二次独立确认：record_github_metric_outcomes 已记第一次观测，
                # 这里凑满第二次，单趟即可把确认下架的仓库置为 not_found
                for outcome in outcomes:
                    if outcome.status != "not_found":
                        continue
                    confirm = fetch_github_repo_metrics(outcome.full_name)
                    if confirm.status == "not_found":
                        repository.record_github_repo_not_found(
                            outcome.full_name, checked_at=_utcnow()
                        )
                        totals["confirmed_not_found"] += 1

            logger.info("批次 %d 完成：%s（游标 %s）", batch_no, counts, after)

        if args.limit and processed >= args.limit:
            break
        if args.interval > 0:
            time.sleep(args.interval)

    summary = {"status": "dry_run" if args.dry_run else "success", **totals}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
