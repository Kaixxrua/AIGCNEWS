from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional

from backend.app.services.ingestion.producthunt_policy import (
    parse_featured_at,
    published_date,
    within_period,
)


def _topics(item: Dict[str, Any]) -> List[str]:
    topics: List[str] = []
    topics_data = item.get("topics") or {}
    if isinstance(topics_data, dict):
        for edge in topics_data.get("edges", []):
            node = edge.get("node", {})
            if isinstance(node, dict) and node.get("name"):
                topics.append(node["name"])
    return topics


def project_api_items(
    edges: List[Dict[str, Any]],
    period: str,
    anchor: date,
    source_channel: str,
    crawl_date_str: str,
) -> Optional[List[Dict[str, Any]]]:
    """Project Product Hunt API edges to the established item dictionaries."""
    results: List[Dict[str, Any]] = []
    for edge in edges:
        node = edge.get("node", {})
        if not node:
            continue

        name = (node.get("name") or "").strip()
        if not name:
            continue

        tagline = (node.get("tagline") or "").strip()
        slug = node.get("slug", "")
        url = node.get("url") or (
            f"https://www.producthunt.com/posts/{slug}" if slug else ""
        )
        votes = int(node.get("votesCount") or 0)
        # commentsCount 不进入投影输出，但坏数据必须拒绝该条目（契约测试要求 ValueError）。
        _comments = int(node.get("commentsCount") or 0)

        featured_at_str = node.get("featuredAt", "")
        feat_date = parse_featured_at(featured_at_str)
        if not within_period(feat_date, period, anchor):
            continue

        topics = _topics(node)
        pub_date = published_date(feat_date, period, anchor, crawl_date_str)
        abstract = tagline
        if topics:
            abstract = f"{tagline} [{', '.join(topics[:3])}]"

        results.append(
            {
                "title": name,
                "abstract": abstract,
                "summary": abstract,
                "url": url,
                "votes": votes,
                "raw_score": float(votes),
                "score": float(votes),
                "source": "producthunt",
                "source_channel": source_channel,
                "channel": source_channel,
                "published_date": pub_date,
                "tags": ["ProductHunt", period] + topics[:5],
                "pdf_url": "",
                "featured_at": featured_at_str,
                "daily_rank": "",
                "weekly_rank": "",
                "monthly_rank": "",
            }
        )

    return results if results else None


def project_html_items(
    posts: List[Dict[str, Any]],
    limit: int,
    period: str,
    anchor: date,
    source_channel: str,
    crawl_date_str: str,
) -> List[Dict[str, Any]]:
    """Project in-window Product Hunt HTML posts to exact item dictionaries."""
    results: List[Dict[str, Any]] = []
    for post in posts:
        if len(results) >= limit:
            break

        featured_at_str = post.get("featuredAt", "")
        feat_date = parse_featured_at(featured_at_str)
        if not within_period(feat_date, period, anchor):
            continue

        name = (post.get("name") or "").strip()
        tagline = (post.get("tagline") or "").strip()
        if not name:
            continue

        slug = post.get("slug", "")
        url = f"https://www.producthunt.com/posts/{slug}" if slug else ""
        launch_score = int(post.get("launchDayScore") or 0)
        latest_score = int(post.get("latestScore") or 0)
        votes = max(launch_score, latest_score)
        topics = _topics(post)
        pub_date = published_date(feat_date, period, anchor, crawl_date_str)
        abstract = tagline
        if topics:
            abstract = f"{tagline} [{', '.join(topics[:3])}]"

        results.append(
            {
                "title": name,
                "abstract": abstract,
                "summary": abstract,
                "url": url,
                "votes": votes,
                "raw_score": float(votes),
                "score": float(votes),
                "source": "producthunt",
                "source_channel": source_channel,
                "channel": source_channel,
                "published_date": pub_date,
                "tags": ["ProductHunt", period] + topics[:5],
                "pdf_url": "",
                "featured_at": featured_at_str,
                "daily_rank": str(post.get("dailyRank") or ""),
                "weekly_rank": str(post.get("weeklyRank") or ""),
                "monthly_rank": str(post.get("monthlyRank") or ""),
            }
        )
    return results


def project_relaxed_html_items(
    posts: List[Dict[str, Any]],
    limit: int,
    period: str,
    source_channel: str,
    crawl_date_str: str,
) -> List[Dict[str, Any]]:
    """Project the established out-of-window HTML fallback dictionaries."""
    results: List[Dict[str, Any]] = []
    for post in posts[:limit]:
        name = (post.get("name") or "").strip()
        tagline = (post.get("tagline") or "").strip()
        if not name:
            continue
        slug = post.get("slug", "")
        url = f"https://www.producthunt.com/posts/{slug}" if slug else ""
        launch_score = int(post.get("launchDayScore") or 0)
        latest_score = int(post.get("latestScore") or 0)
        votes = max(launch_score, latest_score)
        topics = _topics(post)
        results.append(
            {
                "title": name,
                "abstract": (
                    f"{tagline} [{', '.join(topics[:3])}]" if topics else tagline
                ),
                "summary": tagline,
                "url": url,
                "votes": votes,
                "raw_score": float(votes),
                "score": float(votes),
                "source": "producthunt",
                "source_channel": source_channel,
                "channel": source_channel,
                "published_date": crawl_date_str,
                "tags": ["ProductHunt", period] + topics[:5],
                "pdf_url": "",
                "featured_at": post.get("featuredAt", ""),
                "daily_rank": str(post.get("dailyRank") or ""),
                "weekly_rank": str(post.get("weeklyRank") or ""),
                "monthly_rank": str(post.get("monthlyRank") or ""),
            }
        )
    return results
