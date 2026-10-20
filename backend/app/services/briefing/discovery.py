"""Shared public issue identities for sitemap and reader navigation."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any
from urllib.parse import urlencode

from backend.app.repositories.briefing_repository import BriefingReader

INDEX_SOURCES = ("all", "arxiv", "github", "news", "producthunt", "hackernews")
INDEX_WINDOW_DAYS = 90


def briefing_index(repository: BriefingReader, today: date) -> list[dict[str, Any]]:
    since = today - timedelta(days=INDEX_WINDOW_DAYS)
    rows = repository.list_briefing_index(since=since.isoformat(), until=today.isoformat())
    issues = {}
    for row in rows:
        key = str(row.get("date") or "")
        day, _, source = key.partition("_")
        source = source or "all"
        try:
            parsed = date.fromisoformat(day)
        except ValueError:
            continue
        canonical_key = day if source == "all" else f"{day}_{source}"
        if key != canonical_key or parsed.isoformat() != day or not since <= parsed <= today or source not in INDEX_SOURCES:
            continue
        locales = [locale for locale, field in (("zh-CN", "has_zh"), ("en-US", "has_en")) if row.get(field) is True]
        if not locales:
            continue
        issues[(day, source)] = {
            "date": day, "source": source, "locales": locales,
            "modified": row.get("created_at"),
        }
    return sorted(issues.values(), key=lambda item: (item["date"], item["source"]), reverse=True)


def briefing_path(issue: dict[str, Any], locale: str | None = None) -> str:
    query = {"date": issue["date"]}
    if issue["source"] != "all":
        query["type"] = issue["source"]
    if locale:
        query["lang"] = locale
    return "/report?" + urlencode(query)
