#!/usr/bin/env python3
"""X 条目存量 t.co 短链展开回填。

t.co 残留的两类历史形态：
  1. 正文/标题内联 t.co：卡片推文中 X 实体 urls[].expanded_url 本身即
     t.co，采集期位置配对无真实 URL 可换，按"绝不静默丢链接"原样落库；
  2. 译文 translation_zh 内联 t.co：translateTweet 并非总剥 URL（实测
     Zai_org 推文形态），restore_translation_urls 修复前按"已存在"跳过。

回填把存量行的 t.co 经 HTTP 301 解析为目标页地址，重写 title/summary/
translation_zh 及 quote/link_card JSON 内的对应字段。解析失败保留原值
（t.co 仍可经 X 重定向跳转），绝不置空链接。幂等：已展开的行不再匹配
t.co 模式，重跑无副作用。

本机运行（.env 的 POSTGRES_HOST 指向容器网络名，宿主机需覆盖）：
    POSTGRES_HOST=127.0.0.1 python scripts/backfill_x_tco_links.py --dry-run
    POSTGRES_HOST=127.0.0.1 python scripts/backfill_x_tco_links.py \
        --proxy socks5h://127.0.0.1:11080
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.core.postgres_database import postgres_database  # noqa: E402
from backend.app.services.ingestion.sources.x_policy import _TCO_RE  # noqa: E402

DEFAULT_PROXY = "socks5h://127.0.0.1:11080"

# quote/link_card JSON 内需要展开 t.co 的文本字段
_QUOTE_TEXT_KEYS = ("text", "translation_zh")
_LINK_CARD_TEXT_KEYS = ("url",)


def find_tco_links(text: str) -> list[str]:
    """文本里的 t.co 短链列表（去重保序）。"""
    if not text:
        return []
    return list(dict.fromkeys(_TCO_RE.findall(text)))


def rewrite_text(text: str, mapping: dict[str, str]) -> str:
    """按解析映射展开文本内联 t.co；未解析的保留原值。"""
    if not text or not mapping:
        return text
    return _TCO_RE.sub(lambda m: mapping.get(m.group(0), m.group(0)), text)


def _rewrite_json_field(raw: str | None, keys: tuple[str, ...], mapping: dict[str, str]) -> str | None:
    """重写 quote/link_card JSON 文本内指定字段的 t.co；坏 JSON 原样返回不动。"""
    if not raw or not mapping:
        return raw
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        return raw
    if not isinstance(payload, dict):
        return raw
    changed = False
    for key in keys:
        value = payload.get(key)
        if not isinstance(value, str):
            continue
        rewritten = rewrite_text(value, mapping)
        if rewritten != value:
            payload[key] = rewritten
            changed = True
    if not changed:
        return raw
    # 与 upsert_document 同一序列化口径（ensure_ascii=False）
    return json.dumps(payload, ensure_ascii=False)


def rewrite_row(row: dict[str, Any], mapping: dict[str, str]) -> dict[str, str]:
    """计算一行的字段更新集；无变化返回空 dict。"""
    updates: dict[str, str] = {}
    for key in ("title", "summary", "translation_zh"):
        value = row.get(key)
        if not isinstance(value, str) or "https://t.co/" not in value:
            continue
        rewritten = rewrite_text(value, mapping)
        if rewritten != value:
            updates[key] = rewritten
    quote = _rewrite_json_field(row.get("quote"), _QUOTE_TEXT_KEYS, mapping)
    if quote != row.get("quote") and quote is not None:
        updates["quote"] = quote
    link_card = _rewrite_json_field(row.get("link_card"), _LINK_CARD_TEXT_KEYS, mapping)
    if link_card != row.get("link_card") and link_card is not None:
        updates["link_card"] = link_card
    return updates


def curl_redirect_url(link: str, *, proxy: str, timeout: float) -> str:
    """t.co 首跳 301 的 Location；非重定向（安全页/200）或失败返回空串。

    默认走 socks5h 本机隧道（t.co 境内直连不可达）；proxy 为空串则直连。
    """
    cmd = [
        "curl", "-sS", "-o", "/dev/null", "-w", "%{redirect_url}",
        "-m", str(int(timeout)),
    ]
    if proxy:
        cmd += ["-x", proxy]
    cmd.append(link)
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout + 5, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if proc.returncode != 0:
        return ""
    target = proc.stdout.strip()
    # 防环：目标仍是 t.co 短链不算展开成功
    if not target or _TCO_RE.fullmatch(target):
        return ""
    return target


def resolve_tco_links(
    links: list[str],
    *,
    proxy: str,
    timeout: float = 15.0,
    interval: float = 0.2,
    resolver: Callable[..., str] = curl_redirect_url,
) -> dict[str, str]:
    """批量解析 t.co → 目标 URL；失败的条目不进映射（调用方保留原值）。"""
    mapping: dict[str, str] = {}
    for index, link in enumerate(links):
        target = resolver(link, proxy=proxy, timeout=timeout)
        if target:
            mapping[link] = target
        if interval and index + 1 < len(links):
            time.sleep(interval)
    return mapping


def _collect_rows(connection: Any, limit: int) -> list[dict[str, Any]]:
    pattern = "%https://t.co/%"
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT id, title, summary, translation_zh, quote, link_card
            FROM documents
            WHERE source = 'x' AND (
                title LIKE %(pattern)s
                OR summary LIKE %(pattern)s
                OR translation_zh LIKE %(pattern)s
                OR quote LIKE %(pattern)s
                OR link_card LIKE %(pattern)s
            )
            ORDER BY published_at DESC
            LIMIT %(limit)s
            """,
            {"pattern": pattern, "limit": limit},
        )
        return list(cursor.fetchall())


def _apply_updates(connection: Any, doc_id: str, updates: dict[str, str]) -> None:
    assignments = ", ".join(f"{key} = %({key})s" for key in updates)
    with connection.cursor() as cursor:
        cursor.execute(
            f"UPDATE documents SET {assignments} WHERE id = %(id)s",
            {**updates, "id": doc_id},
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Expand stored t.co short links in X documents via HTTP redirects"
    )
    parser.add_argument("--proxy", default=DEFAULT_PROXY, help="代理解析 t.co（空串=直连）")
    parser.add_argument("--limit", type=int, default=2000, help="单轮最多扫描的行数")
    parser.add_argument("--timeout", type=float, default=15.0, help="单条解析超时秒数")
    parser.add_argument("--interval", type=float, default=0.2, help="解析请求间隔秒数")
    parser.add_argument("--dry-run", action="store_true", help="只统计不写数据库")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    with postgres_database.transaction() as connection:
        rows = _collect_rows(connection, args.limit)
    unique_links = sorted({
        link
        for row in rows
        for field in (row.get("title"), row.get("summary"), row.get("translation_zh"), row.get("quote"), row.get("link_card"))
        for link in find_tco_links(field or "")
    })
    print(f"[backfill-x-tco] 候选行 {len(rows)}，唯一 t.co {len(unique_links)} 个")

    mapping = resolve_tco_links(
        unique_links, proxy=args.proxy, timeout=args.timeout, interval=args.interval,
    )
    print(f"[backfill-x-tco] 解析成功 {len(mapping)}/{len(unique_links)}")

    changed = 0
    for row in rows:
        updates = rewrite_row(row, mapping)
        if not updates:
            continue
        changed += 1
        if args.dry_run:
            print(f"[dry-run] {row['id']}: 更新字段 {sorted(updates)}")
            continue
        with postgres_database.transaction() as connection:
            _apply_updates(connection, str(row["id"]), updates)
    print(f"[backfill-x-tco] {'将更新' if args.dry_run else '已更新'} {changed} 行")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
