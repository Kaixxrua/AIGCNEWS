from __future__ import annotations

"""X/Twitter 采集策略层：纯函数，无副作用。

职责：
  - watchlist 解析（env 字符串 → handle 列表）
  - 推文过滤（推广/转推/订阅专属不入库）
  - 互动分计算（与 HN points 同量级的 raw_score）
  - Tweet 对象 → 标准条目 dict 投影

分层约定见 base_crawler.py 文档字符串：sources/*_policy.py 只做
dict/对象进、dict 出的纯变换，transport 负责一切 IO。
"""

import logging
import math
from datetime import datetime, timezone
from typing import Any, Iterable

logger = logging.getLogger(__name__)

X_SOURCE = "x"
X_CHANNEL = "x_daily_watchlist"

_TWEET_TIME_FORMAT = "%a %b %d %H:%M:%S %z %Y"


def parse_watch_handles(raw: str) -> list[str]:
    """解析逗号/换行分隔的 handle 配置：去 '@'、小写归一、去重保序。"""
    handles: list[str] = []
    seen: set[str] = set()
    for part in raw.replace("\n", ",").split(","):
        handle = part.strip().lstrip("@").strip().lower()
        if handle and handle not in seen:
            seen.add(handle)
            handles.append(handle)
    return handles


def is_ingestible_tweet(tweet: Any) -> bool:
    """过滤不入库的推文：推广内容、转推、订阅专属。

    推广必须过滤：twitter-cli 的 fetch_user_tweets 请求带
    includePromotedContent=True，广告会混入用户时间线。
    """
    if getattr(tweet, "is_promoted", False):
        return False
    if getattr(tweet, "is_retweet", False):
        return False
    if getattr(tweet, "is_subscriber_only", False):
        return False
    return bool(getattr(tweet, "id", "") and getattr(tweet, "text", ""))


def compute_engagement_score(
    *,
    likes: int = 0,
    retweets: int = 0,
    replies: int = 0,
    bookmarks: int = 0,
    views: int = 0,
) -> float:
    """互动分：likes + 3·RT + 2·replies + 5·bookmarks + 0.5·log10(views)。

    权重沿用 twitter-cli 内置排序公式（filter.py DEFAULT_WEIGHTS），
    量级（几十~几千）与 HN points 相当，现有排行归一化不失真。
    """
    return (
        float(likes)
        + 3.0 * retweets
        + 2.0 * replies
        + 5.0 * bookmarks
        + 0.5 * math.log10(max(views, 1))
    )


def parse_tweet_datetime(created_at: str) -> datetime | None:
    """legacy 时间串 → UTC datetime；解析失败返回 None。"""
    if not created_at:
        return None
    try:
        parsed = datetime.strptime(created_at, _TWEET_TIME_FORMAT)
        return parsed.astimezone(timezone.utc)
    except (ValueError, TypeError) as exc:
        logger.debug("[XPolicy] bad tweet created_at %r: %s", created_at, exc)
        return None


def parse_tweet_date(created_at: str) -> str:
    """legacy 时间串 → UTC 日期 YYYY-MM-DD（与 HN policy 同一时区约定）。

    解析失败返回空串并 debug 日志（HN 先例：不因此丢弃条目）。
    """
    parsed = parse_tweet_datetime(created_at)
    return parsed.strftime("%Y-%m-%d") if parsed else ""


def compose_tweet_url(screen_name: str, tweet_id: str) -> str:
    """拼接推文 canonical URL（Tweet 对象不带 url 字段）。"""
    return f"https://x.com/{screen_name}/status/{tweet_id}"


def _project_tweet_media(tweet: Any) -> list[dict]:
    """把 twitter-cli 的 Tweet.media 投影为可序列化的元数据列表。

    结构: [{"type": "photo|video|animated_gif", "url": "...", "width": 123, "height": 456}]
    视频/GIF 经 x_transport 封面补丁回填 poster_url（X 官方封面图）时
    带出该键；无补丁对象/照片不带，保持旧形状不变。
    """
    media = getattr(tweet, "media", None) or []
    items: list[dict] = []
    for item in media:
        if not getattr(item, "url", ""):
            continue
        entry = {
            "type": str(getattr(item, "type", "") or ""),
            "url": str(getattr(item, "url", "") or ""),
            "width": getattr(item, "width", None),
            "height": getattr(item, "height", None),
        }
        poster = str(getattr(item, "poster_url", "") or "")
        if poster:
            entry["poster_url"] = poster
        items.append(entry)
    return items


def project_tweets(
    tweets: Iterable[Any],
    *,
    limit: int,
    source_channel: str = X_CHANNEL,
) -> list[dict]:
    """过滤 → 打分 → 降序 → 截断 → 投影为标准条目 dict。

    输入为 twitter-cli 的 Tweet dataclass（鸭子类型，测试可用同类对象）。
    合并所有账号的推文统一排序，rank_in_period 从 1 开始。
    """
    ingestible = [tweet for tweet in tweets if is_ingestible_tweet(tweet)]

    def _score(tweet: Any) -> float:
        metrics = getattr(tweet, "metrics", None)
        return compute_engagement_score(
            likes=int(getattr(metrics, "likes", 0) or 0),
            retweets=int(getattr(metrics, "retweets", 0) or 0),
            replies=int(getattr(metrics, "replies", 0) or 0),
            bookmarks=int(getattr(metrics, "bookmarks", 0) or 0),
            views=int(getattr(metrics, "views", 0) or 0),
        )

    ranked = sorted(ingestible, key=_score, reverse=True)[:limit]

    results: list[dict] = []
    for rank, tweet in enumerate(ranked, start=1):
        tweet_id = str(getattr(tweet, "id", ""))
        author = getattr(tweet, "author", None)
        screen_name = str(getattr(author, "screen_name", "") or "")
        author_name = str(getattr(author, "name", "") or "")
        author_avatar_url = str(
            getattr(author, "profile_image_url", "")
            or getattr(author, "profile_image_url_https", "")
            or ""
        )
        text = str(getattr(tweet, "text", "") or "")
        metrics = getattr(tweet, "metrics", None)
        score = _score(tweet)
        media = _project_tweet_media(tweet)
        created_at = str(getattr(tweet, "created_at", "") or "")
        parsed_dt = parse_tweet_datetime(created_at)
        results.append(
            {
                "title": " ".join(text.split()),
                "url": compose_tweet_url(screen_name, tweet_id),
                "abstract": text,
                "summary": text,
                "source": X_SOURCE,
                "source_channel": source_channel,
                "channel": source_channel,
                "score": score,
                "raw_score": score,
                "likes": int(getattr(metrics, "likes", 0) or 0),
                "retweets": int(getattr(metrics, "retweets", 0) or 0),
                "replies": int(getattr(metrics, "replies", 0) or 0),
                "quotes": int(getattr(metrics, "quotes", 0) or 0),
                "views": int(getattr(metrics, "views", 0) or 0),
                "bookmarks": int(getattr(metrics, "bookmarks", 0) or 0),
                "published_at": parsed_dt.isoformat() if parsed_dt else "",
                "published_date": parsed_dt.strftime("%Y-%m-%d") if parsed_dt else "",
                "tweet_id": tweet_id,
                "author": screen_name,
                "author_name": author_name,
                "author_avatar_url": author_avatar_url,
                "rank_in_period": rank,
                "tags": [X_SOURCE, "daily", screen_name],
                "media": media,
            }
        )
    return results
