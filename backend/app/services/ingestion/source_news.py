from __future__ import annotations

"""Techmeme 新闻数据源：RSS + 主页 HTML 双通道采集。

数据源说明：
  Techmeme (https://www.techmeme.com/) 是业界公认的科技/AI 新闻聚合站。

  ⚠️ RSS 条目上限说明：
  Techmeme 的 RSS Feed (feed.xml) 只提供约 15 条最新滚动条目，
  这是 Techmeme 官方的设计限制，无法通过参数增加。
  因此本模块采用双通道策略：
    1. RSS Feed（约 15 条）：结构化数据，有标题/摘要/发布时间
    2. 主页 HTML 解析（约 30-50 条）：补充 RSS 未覆盖的条目

  两个通道合并去重后，通常可获取 30-50 条独特新闻。

-----------------------------------------------------------------------
RAG 导入设计思路
-----------------------------------------------------------------------
每条 Techmeme 新闻导入 RAG 时携带以下字段：

1. title         → 主要向量化文本（语义搜索的核心）
2. summary       → 辅助上下文（去除 HTML 标签的纯文本摘要）
3. url           → 溯源引用（citation）
4. published_date → 时效性过滤
5. source="news" + feed_name="Techmeme" → 来源标签
6. score / rank_in_period → Techmeme 排列顺序即编辑重要性排序
-----------------------------------------------------------------------
"""

import logging
import re
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import List, Optional

logger = logging.getLogger(__name__)

TECHMEME_RSS_URL = "https://www.techmeme.com/feed.xml"
TECHMEME_HOME_URL = "https://www.techmeme.com/"

# Techmeme RSS 官方上限：约 15 条滚动更新条目
# 这是 Techmeme 的设计限制，不是代码 bug
_RSS_MAX_ITEMS = 15


def _parse_entry_date(entry) -> str:
    """解析 RSS entry 的发布日期，返回 YYYY-MM-DD 字符串。"""
    if hasattr(entry, "published_parsed") and entry.published_parsed:
        t = entry.published_parsed
        return f"{t.tm_year:04d}-{t.tm_mon:02d}-{t.tm_mday:02d}"

    published = (entry.get("published") or entry.get("updated") or "").strip()
    if published:
        try:
            return parsedate_to_datetime(published).date().isoformat()
        except Exception:
            pass

    return ""


def _clean_html(text: str) -> str:
    """去除 HTML 标签和 HTML 实体，保留纯文本。"""
    text = re.sub(r"<[^>]+>", " ", text)
    # 解码常见 HTML 实体
    import html as _html

    text = _html.unescape(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _within_period(day_str: str, period: str, anchor: date) -> bool:
    """判断日期字符串是否在指定周期窗口内。

    daily  → anchor-1 ~ anchor（接受今天和昨天，兼容美东时区差异）
    weekly → anchor-6 ~ anchor
    monthly→ anchor-29 ~ anchor
    """
    if not day_str:
        return True

    try:
        day = datetime.fromisoformat(day_str[:10]).date()
    except ValueError:
        return True

    period = (period or "daily").lower().strip()
    if period == "weekly":
        start = anchor - timedelta(days=6)
    elif period == "monthly":
        start = anchor - timedelta(days=29)
    else:
        # daily: 接受今天和昨天，避免美东时区导致当天新闻被过滤
        start = anchor - timedelta(days=1)
    return start <= day <= anchor


def _fetch_rss_articles(
    limit: int,
    period: str,
    anchor: date,
    source_channel: str,
) -> List[dict]:
    """从 Techmeme RSS 采集文章。

    ⚠️ Techmeme RSS 单次最多返回约 15 条（官方限制），
    这不是代码层面的 bug，而是数据源本身的约束。
    """
    try:
        import feedparser  # type: ignore
    except ImportError:
        logger.error("[News] feedparser 未安装，请执行: pip install feedparser")
        return []

    try:
        import httpx

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
        }
        with httpx.Client(timeout=20, follow_redirects=True, headers=headers) as client:
            response = client.get(TECHMEME_RSS_URL)
            response.raise_for_status()
        feed = feedparser.parse(response.content)
    except Exception as exc:
        logger.error("[News] 无法获取或解析 Techmeme RSS: %s", exc)
        return []

    total_entries = len(feed.entries)
    logger.info(
        "[News] Techmeme RSS 返回 %d 条条目（官方上限约 %d 条）",
        total_entries,
        _RSS_MAX_ITEMS,
    )

    results: List[dict] = []
    rank = 1

    for entry in feed.entries[:_RSS_MAX_ITEMS]:
        if len(results) >= limit:
            break

        title = entry.get("title", "").strip()
        if not title:
            continue

        raw_summary = entry.get("summary", "") or entry.get("description", "") or ""
        summary = _clean_html(raw_summary)[:600]

        url = entry.get("link", "")
        published = _parse_entry_date(entry)

        if not _within_period(published, period, anchor):
            rank += 1
            continue

        results.append(
            {
                "title": title,
                "abstract": summary,
                "summary": summary,
                "url": url,
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


def _fetch_homepage_articles(
    limit: int,
    period: str,
    anchor: date,
    source_channel: str,
    existing_urls: set,
) -> List[dict]:
    """从 Techmeme 主页 HTML 解析额外的新闻条目（补充 RSS 不足）。

    解析 Techmeme 主页的新闻标题和链接，获取 RSS 未覆盖的条目。
    Techmeme 主页通常包含 30-50 条新闻。
    """
    import httpx

    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        with httpx.Client(timeout=20, follow_redirects=True, headers=headers) as client:
            resp = client.get(TECHMEME_HOME_URL)
            resp.raise_for_status()
            html = resp.text
    except Exception as exc:
        logger.warning(
            "[News] Techmeme 主页抓取失败（非致命，RSS 数据仍可用）: %s", exc
        )
        return []

    if not html or len(html) < 1000:
        logger.warning(
            "[News] Techmeme 主页内容异常（长度=%d），跳过 HTML 解析",
            len(html) if html else 0,
        )
        return []

    # 解析 Techmeme 主页的新闻条目
    # Techmeme 的主要新闻标题在 class="topmenu" 和主内容区域
    # 每个新闻块通常包含一个 strong 标签内的链接
    results: List[dict] = []

    # 匹配主要新闻标题链接：<a href="..." class="ourHed">标题</a>
    # Techmeme 使用 class="ourHed" 标记编辑选定的标题
    patterns = [
        # 主要标题（ourHed class）
        re.compile(
            r'<a[^>]+class="ourHed"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.DOTALL
        ),
        # 备用模式：strong 内的链接
        re.compile(r'<strong><a[^>]+href="([^"]+)"[^>]*>(.*?)</a></strong>', re.DOTALL),
    ]

    seen_urls = set(existing_urls)
    rank_offset = len(existing_urls) + 1

    for pattern in patterns:
        for m in pattern.finditer(html):
            if len(results) >= limit:
                break

            url = m.group(1).strip()
            title = _clean_html(m.group(2)).strip()

            if not title or not url:
                continue

            # 跳过已在 RSS 中出现的 URL
            if url in seen_urls:
                continue
            seen_urls.add(url)

            # 跳过 Techmeme 内部链接
            if "techmeme.com" in url:
                continue

            results.append(
                {
                    "title": title,
                    "abstract": title,  # 主页没有摘要，用标题代替
                    "summary": title,
                    "url": url,
                    "pdf_url": "",
                    "source": "news",
                    "source_channel": source_channel,
                    "channel": source_channel,
                    "score": 1.5,  # 主页补充数据分数略低于 RSS
                    "raw_score": 1.5,
                    "rank_in_period": rank_offset + len(results),
                    "tags": ["Techmeme", period, "html"],
                    "published_date": anchor.isoformat(),  # 主页无精确时间，用 anchor 日期
                    "feed_name": "Techmeme",
                }
            )

    logger.info(
        "[News] Techmeme 主页 HTML 额外提取 %d 条（去重后，排除 RSS 已有的 %d 条）",
        len(results),
        len(existing_urls),
    )
    return results


def fetch_news_articles(
    limit: int = 30,
    period: str = "daily",
    target_date: Optional[str] = None,
) -> List[dict]:
    """从 Techmeme 采集新闻：RSS + 主页 HTML 双通道，合并去重。

    ⚠️ 条目数量说明：
    - Techmeme RSS 单次最多约 15 条（官方限制，非代码 bug）
    - 主页 HTML 可补充额外 15-30 条
    - 合并去重后通常 30-45 条

    返回字段兼容 pipeline._to_documents() 格式：
      - title: 新闻标题
      - abstract / summary: 纯文本摘要
      - url: 新闻链接
      - source: "news"
      - source_channel: "techmeme_daily_rss"
      - score / raw_score: RSS=2.0, HTML补充=1.5
      - rank_in_period: 在当日 Techmeme 榜单中的排名（1=最重要）
      - tags: ["Techmeme", period]
      - published_date: ISO 日期字符串
      - feed_name: "Techmeme"
    """
    period = (period or "daily").lower().strip()
    # 使用 CST（UTC+8）本地时间作为 anchor，避免服务器 UTC 时差导致日期偏差
    _tz_cst = timezone(timedelta(hours=8))
    anchor = datetime.now(_tz_cst).date()
    if target_date:
        try:
            anchor = date.fromisoformat(target_date)
        except ValueError:
            logger.warning("[News] target_date 非法，回退到今天: %s", target_date)

    source_channel = "techmeme_daily_rss"

    # 通道 1: RSS Feed（约 15 条，结构化数据）
    rss_articles = _fetch_rss_articles(limit, period, anchor, source_channel)
    logger.info("[News] RSS 通道获取 %d 条", len(rss_articles))

    # 通道 2: 主页 HTML（补充 RSS 未覆盖的条目）
    rss_urls = {a.get("url", "") for a in rss_articles if a.get("url")}
    remaining = max(0, limit - len(rss_articles))

    html_articles: List[dict] = []
    if remaining > 0:
        html_articles = _fetch_homepage_articles(
            limit=remaining,
            period=period,
            anchor=anchor,
            source_channel=source_channel,
            existing_urls=rss_urls,
        )

    # 合并（RSS 优先，HTML 补充）
    results = rss_articles + html_articles

    logger.info(
        "[News] Techmeme 双通道合计: RSS %d + HTML %d = %d 条 (period=%s, anchor=%s)",
        len(rss_articles),
        len(html_articles),
        len(results),
        period,
        anchor.isoformat(),
    )
    return results
