"""Pure personal-tracking policy shared by repositories and services."""

from __future__ import annotations

import ipaddress
import re
from datetime import datetime, timedelta, timezone
from html import escape, unescape
from typing import Any
from urllib.parse import quote, urlsplit

from backend.app.domain.membership import resolve_effective_tier
from backend.app.domain.public_content import (
    sanitize_public_resource_url,
    sanitize_public_text,
)

CST = timezone(timedelta(hours=8))
FREE_RULE_LIMIT = 1
MEMBER_RULE_LIMIT = 10
DIGEST_ITEM_LIMIT = 50
# 关键词热度飙升（vip）：最近 24 小时至少 5 条，且不少于前 7 天日均的 3 倍。
SURGE_MIN_COUNT = 5
SURGE_RATIO = 3
SURGE_BASELINE_DAYS = 7


class TrackingError(Exception):
    def __init__(self, code: str, status: int = 400) -> None:
        super().__init__(code)
        self.code = code
        self.status = status


def is_member(user: dict[str, Any], now: datetime | None = None) -> bool:
    tier = resolve_effective_tier(
        user.get("membership_tier"), user.get("membership_expires_at"), now=now
    )
    return tier == "member"


def rule_limit(user: dict[str, Any], now: datetime | None = None) -> int:
    return MEMBER_RULE_LIMIT if is_member(user, now) else FREE_RULE_LIMIT


def active_rules(rules: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    return [row for row in sorted(rules, key=lambda row: row["id"]) if row["enabled"]][
        :limit
    ]


def public_link(value: str) -> str | None:
    try:
        candidate = sanitize_public_resource_url(value)
        if not candidate or not candidate.startswith("https://"):
            return None
        host = (urlsplit(candidate).hostname or "").rstrip(".").lower()
        if "." not in host or host.endswith((".local", ".internal", ".localhost")):
            return None
        try:
            if not ipaddress.ip_address(host).is_global:
                return None
        except ValueError:
            if not re.search(r"\.[a-z][a-z0-9-]*$", host):
                return None
        return candidate
    except ValueError:
        return None


def plain_text(value: object, limit: int) -> str:
    text = re.sub(r"<[^>]*>", "", unescape(str(value or "")))
    return " ".join(sanitize_public_text(text).split())[:limit]


def clean_item(row: dict[str, Any], query: str) -> dict[str, Any] | None:
    url = public_link(str(row.get("url") or ""))
    if not url:
        return None
    return {
        "observed_at": row["observed_at"].isoformat(),
        "key": str(row["key"]),
        "title": plain_text(row.get("title"), 200),
        "url": url,
        "summary": plain_text(row.get("summary"), 280),
        "source": str(row["source"]),
        "matched_rules": [query],
    }


def detect_surge(query: str, matched: list[int], totals: list[int]) -> dict[str, Any] | None:
    """判断一条关键词规则是否热度飙升。

    两个列表按 24 小时倒数分桶，下标 0 是最近 24 小时：matched 是规则命中数，
    totals 是同来源同一天的全部内容数。totals 为 0 的日子视为采集中断，不计入
    日均；前 7 天全部中断时无从比较，不报飙升。
    """
    days = list(zip(matched, totals))
    if not days:
        return None
    count = days[0][0]
    history = [hits for hits, total in days[1 : SURGE_BASELINE_DAYS + 1] if total > 0]
    if count < SURGE_MIN_COUNT or not history:
        return None
    baseline = sum(history) / len(history)
    if count < SURGE_RATIO * max(baseline, 1):
        return None
    return {"query": query, "count": count, "baseline": round(baseline, 1)}


def render_digest(digest: dict[str, Any]) -> str:
    def text(value: str) -> str:
        return escape(re.sub(r"[\[\]*\x60#]", "", value), quote=True)

    lines = [f"# 我的 AI 情报 · {digest['issue_date']}", ""]
    surges = digest.get("surges") or []
    for surge in surges:
        lines.append(
            f"> 热度飙升：「{text(surge['query'])}」近 24 小时 {int(surge['count'])} 条，"
            f"前 7 天日均 {float(surge['baseline']):g} 条"
        )
    if surges:
        lines.append("")
    for item in digest["items"]:
        url = public_link(item["url"])
        if not url:
            continue
        url = escape(quote(url, safe=":/?=&%+@~!$,-._"), quote=True)
        lines.extend(
            [
                f"## [{text(item['title'])}]({url})",
                text(item["summary"]),
                f"匹配：{text('、'.join(item['matched_rules']))}",
                "",
            ]
        )
    if digest["truncated"]:
        lines.append("本期展示最近 50 条匹配内容，可缩小追踪范围以减少遗漏。")
    return "\n".join(lines)
