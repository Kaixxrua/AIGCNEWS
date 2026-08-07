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
import re
from datetime import datetime, timedelta, timezone
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


_TZ_CST = timezone(timedelta(hours=8))


def filter_tweets_to_snapshot_date(tweets: Iterable[Any], snapshot_date: str) -> list[Any]:
    """只保留发布时间落在 snapshot_date（CST 物理日）内的推文。

    snapshot_date 是 CST 日历日（与 base_crawler.today_cst 同一约定）；推文
    created_at 解析为 UTC 后换算 UTC+8 再比日期。watchlist 抓取返回账号近期
    N 条、不做时间过滤会把数周前的旧推文混进当天日榜快照。
    created_at 解析失败的条目无法证明属于当天，一并排除。
    """
    if not snapshot_date:
        return list(tweets)
    fresh: list[Any] = []
    for tweet in tweets:
        parsed = parse_tweet_datetime(str(getattr(tweet, "created_at", "") or ""))
        if parsed is None:
            continue
        if parsed.astimezone(_TZ_CST).date().isoformat() == snapshot_date:
            fresh.append(tweet)
    return fresh


def compose_tweet_url(screen_name: str, tweet_id: str) -> str:
    """拼接推文 canonical URL（Tweet 对象不带 url 字段）。"""
    return f"https://x.com/{screen_name}/status/{tweet_id}"


_TCO_RE = re.compile(r"https://t\.co/[A-Za-z0-9]+")
_TRAILING_TCO_RE = re.compile(r"\s*https://t\.co/[A-Za-z0-9]+\s*$")


def _strip_media_tco(text: str, media: list[dict]) -> str:
    """剥离 full_text 尾部由 X 自动追加的媒体 t.co 链接。

    X 页面有媒体附件时不显示该链接（媒体卡片取而代之），仅有媒体列
    为空时保留。已知边界：媒体+引用复合推文尾部可能是引用链接，一并
    剥掉属可接受误差（组合罕见）。
    """
    if not media:
        return text
    return _TRAILING_TCO_RE.sub("", text)


def _expanded_urls(urls: Any) -> list[str]:
    return [str(u).strip() for u in (urls or []) if str(u).strip()]


def clean_tweet_display_text(text: str, media: list[dict], urls: Any) -> str:
    """把 full_text 转成 X 页面式显示文本：剥媒体尾巴 + t.co 展开为真实 URL。

    twitter-cli 的 Tweet.urls 来自 entities.urls[].expanded_url，实体序与
    文中 t.co 出现序一致（X 按文本顺序生成实体），故按位置配对展开；
    数量不齐时未配对的 t.co 原样保留，绝不静默丢链接。
    """
    cleaned = _strip_media_tco(text, media)
    expanded = _expanded_urls(urls)
    if not expanded:
        return cleaned
    iterator = iter(expanded)
    return _TCO_RE.sub(lambda m: next(iterator, m.group(0)), cleaned)


def restore_translation_urls(translation: str, source_text: str, media: list[dict], urls: Any) -> str:
    """补回 X 译文丢失的链接：translateTweet 响应会剥掉全部 URL。

    媒体尾巴不补（媒体区已单独渲染）；t.co 或其展开式任一已在译文中
    出现视为未丢失，不重复追加。缺失链接按实体序追加到译文末尾，
    与 X 页面「翻译帖子」视图（译文 + 实体链接）对齐。
    """
    cleaned = _strip_media_tco(source_text, media)
    links = _TCO_RE.findall(cleaned)
    if not links:
        return translation
    expanded = _expanded_urls(urls)
    missing: list[str] = []
    for index, tco in enumerate(links):
        target = expanded[index] if index < len(expanded) else tco
        if tco in translation or target in translation:
            continue
        missing.append(target)
    if not missing:
        return translation
    return translation.rstrip() + "\n" + "\n".join(missing)


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
        # media 先于 text 计算：剥媒体 t.co 尾巴依赖媒体列
        media = _project_tweet_media(tweet)
        text = clean_tweet_display_text(
            str(getattr(tweet, "text", "") or ""),
            media,
            getattr(tweet, "urls", None),
        )
        metrics = getattr(tweet, "metrics", None)
        score = _score(tweet)
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
