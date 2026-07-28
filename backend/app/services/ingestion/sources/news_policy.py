from __future__ import annotations

import html
import re
from datetime import date, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Any, Iterable, Mapping

RSS_MAX_ITEMS = 15


def parse_rss(content: bytes) -> Any:
    import feedparser  # type: ignore

    return feedparser.parse(content)


def clean_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def parse_entry_date(entry: Any) -> str:
    published_parsed = getattr(entry, "published_parsed", None)
    if published_parsed:
        return (
            f"{published_parsed.tm_year:04d}-"
            f"{published_parsed.tm_mon:02d}-"
            f"{published_parsed.tm_mday:02d}"
        )
    published = (entry.get("published") or entry.get("updated") or "").strip()
    if published:
        try:
            return parsedate_to_datetime(published).date().isoformat()
        except Exception:
            pass
    return ""


def within_period(day_str: str, period: str, anchor: date) -> bool:
    if not day_str:
        return True
    try:
        day = datetime.fromisoformat(day_str[:10]).date()
    except ValueError:
        return True
    normalized_period = (period or "daily").lower().strip()
    if normalized_period == "weekly":
        start = anchor - timedelta(days=6)
    elif normalized_period == "monthly":
        start = anchor - timedelta(days=29)
    else:
        start = anchor - timedelta(days=1)
    return start <= day <= anchor


def project_rss_entries(
    entries: Iterable[Any],
    *,
    limit: int,
    period: str,
    anchor: date,
    source_channel: str,
) -> list[dict]:
    results: list[dict] = []
    rank = 1
    for entry in list(entries)[:RSS_MAX_ITEMS]:
        if len(results) >= limit:
            break
        title = entry.get("title", "").strip()
        if not title:
            continue
        raw_summary = entry.get("summary", "") or entry.get("description", "") or ""
        summary = clean_html(raw_summary)[:600]
        published = parse_entry_date(entry)
        if not within_period(published, period, anchor):
            rank += 1
            continue
        results.append(
            {
                "title": title,
                "abstract": summary,
                "summary": summary,
                "url": entry.get("link", ""),
                "pdf_url": "",
                "source": "news",
                "source_channel": source_channel,
                "channel": source_channel,
                "score": 2.0,
                "raw_score": 2.0,
                "rank_in_period": rank,
                "tags": ["Techmeme", period],
                "published_date": published,
                "feed_name": "Techmeme",
            }
        )
        rank += 1
    return results


_HOMEPAGE_PATTERNS = (
    re.compile(
        r'<a[^>]+class="ourHed"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
        re.DOTALL,
    ),
    re.compile(
        r'<strong><a[^>]+href="([^"]+)"[^>]*>(.*?)</a></strong>',
        re.DOTALL,
    ),
)


def extract_homepage_matches(page: str) -> list[tuple[str, str]]:
    return [
        (match.group(1), match.group(2))
        for pattern in _HOMEPAGE_PATTERNS
        for match in pattern.finditer(page)
    ]


def project_homepage_matches(
    matches: Iterable[tuple[str, str]],
    *,
    limit: int,
    period: str,
    anchor: date,
    source_channel: str,
    existing_urls: set[str],
) -> list[dict]:
    results: list[dict] = []
    seen_urls = set(existing_urls)
    rank_offset = len(existing_urls) + 1
    for raw_url, raw_title in matches:
        if len(results) >= limit:
            break
        url = raw_url.strip()
        title = clean_html(raw_title).strip()
        if not title or not url or url in seen_urls:
            continue
        seen_urls.add(url)
        if "techmeme.com" in url:
            continue
        results.append(
            {
                "title": title,
                "abstract": title,
                "summary": title,
                "url": url,
                "pdf_url": "",
                "source": "news",
                "source_channel": source_channel,
                "channel": source_channel,
                "score": 1.5,
                "raw_score": 1.5,
                "rank_in_period": rank_offset + len(results),
                "tags": ["Techmeme", period, "html"],
                "published_date": anchor.isoformat(),
                "feed_name": "Techmeme",
            }
        )
    return results


def merge_articles(
    rss_articles: Iterable[Mapping[str, Any]],
    html_articles: Iterable[Mapping[str, Any]],
) -> list[dict]:
    return [dict(item) for item in rss_articles] + [dict(item) for item in html_articles]
