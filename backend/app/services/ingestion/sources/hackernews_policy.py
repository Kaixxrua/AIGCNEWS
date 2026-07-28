from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

MAX_AGE_HOURS = 24


def is_story(item: Mapping[str, Any] | None) -> bool:
    return bool(
        item
        and item.get("type") == "story"
        and not item.get("dead")
        and not item.get("deleted")
    )


def filter_recent_stories(
    stories: Iterable[Mapping[str, Any]],
    *,
    now_ts: float,
    max_age_hours: int = MAX_AGE_HOURS,
) -> list[dict]:
    cutoff_ts = now_ts - (max_age_hours * 3600)
    return [dict(story) for story in stories if story.get("time", 0) >= cutoff_ts]


def sort_by_score(stories: Iterable[Mapping[str, Any]]) -> list[dict]:
    return sorted(
        (dict(story) for story in stories),
        key=lambda story: int(story.get("score", 0)),
        reverse=True,
    )


def project_stories(
    stories: Iterable[Mapping[str, Any]],
    *,
    limit: int,
    source_channel: str = "hn_daily_html",
) -> list[dict]:
    results: list[dict] = []
    for rank, story in enumerate(list(stories)[:limit], start=1):
        hn_id = str(story.get("id", ""))
        story_time = story.get("time", 0)
        published_date = ""
        if story_time:
            try:
                published_date = datetime.fromtimestamp(
                    story_time,
                    tz=timezone.utc,
                ).strftime("%Y-%m-%d")
            except Exception:
                pass
        title = story.get("title", "")
        points = int(story.get("score", 0))
        results.append(
            {
                "title": title,
                "url": story.get("url")
                or f"https://news.ycombinator.com/item?id={hn_id}",
                "abstract": title,
                "summary": title,
                "source": "hackernews",
                "source_channel": source_channel,
                "channel": source_channel,
                "score": float(points),
                "raw_score": float(points),
                "votes": points,
                "comments": int(story.get("descendants", 0)),
                "published_date": published_date,
                "hn_id": hn_id,
                "author": story.get("by", ""),
                "rank_in_period": rank,
                "tags": ["hackernews", "daily", "top30"],
            }
        )
    return results
