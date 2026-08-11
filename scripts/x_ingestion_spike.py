#!/usr/bin/env python3
"""X/Twitter 采集 spike：用真实 cookie 验证 transport + policy 全链路。

上线前验收与 cookie 重配后的标准检查手段（见 docs/x-source-runbook.md）。

用法：
    python scripts/x_ingestion_spike.py                      # watchlist 首个账号拉 5 条
    python scripts/x_ingestion_spike.py --handle openai --count 5

凭据：读取公共仓根目录 .env 的 TWITTER_AUTH_TOKEN / TWITTER_CT0 /
TWITTER_WATCH_HANDLES（公共仓位置经 AIGCNEWS_PUBLIC_REPO 或同级
兄弟检出解析）。

退出码：0 = 拉到至少 1 条可入库推文；1 = 凭据缺失/失效/限流/0 条。
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

# 私有仓根目录 + 公共仓根目录同时上 sys.path（公共仓位置：
# AIGCNEWS_PUBLIC_REPO 环境变量，缺省取同级兄弟检出 ../AIGCNEWS）。
PRIVATE_ROOT = Path(__file__).resolve().parents[1]
PUBLIC_ROOT = Path(
    os.environ.get("AIGCNEWS_PUBLIC_REPO", PRIVATE_ROOT.parent / "AIGCNEWS")
).resolve()
for path in (str(PRIVATE_ROOT), str(PUBLIC_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

from dotenv import load_dotenv

load_dotenv(PUBLIC_ROOT / ".env")

from aigcnews_private.sources import x_transport
from backend.app.services.ingestion.sources import x_policy


async def _run(handle: str, count: int) -> int:
    transport = x_transport.XTransport()
    try:
        tweets_by_handle = await transport.fetch_watchlist_tweets([handle], count)
    except (
        x_transport.XAuthNotConfigured,
        x_transport.XAuthAbort,
        x_transport.XRateLimitAbort,
    ) as exc:
        print(f"[spike] 中止级失败: {exc}", file=sys.stderr)
        return 1

    tweets = tweets_by_handle.get(handle, [])
    if not tweets:
        print(
            f"[spike] @{handle} 未拉到推文（账号不存在/已改名/被跳过）",
            file=sys.stderr,
        )
        return 1

    items = x_policy.project_tweets(tweets, limit=count)
    print(f"[spike] @{handle} 拉到 {len(tweets)} 条，可入库 {len(items)} 条：")
    for item in items:
        print(
            f"  #{item['rank_in_period']} score={item['score']:.1f} "
            f"{item['published_date']} {item['url']}"
        )
        print(f"     {item['title']}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="X/Twitter 采集 spike（真实 cookie 全链路验证）"
    )
    parser.add_argument(
        "--handle",
        default="",
        help="目标账号（缺省取 TWITTER_WATCH_HANDLES 第一个）",
    )
    parser.add_argument("--count", type=int, default=5, help="抓取条数（默认 5）")
    args = parser.parse_args()

    handle = args.handle.strip().lstrip("@").lower()
    if not handle:
        handles = x_policy.parse_watch_handles(
            os.environ.get("TWITTER_WATCH_HANDLES", "")
        )
        if not handles:
            print(
                "[spike] 未指定 --handle 且 TWITTER_WATCH_HANDLES 为空",
                file=sys.stderr,
            )
            return 1
        handle = handles[0]

    return asyncio.run(_run(handle, max(args.count, 1)))


if __name__ == "__main__":
    sys.exit(main())
