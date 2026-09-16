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
from datetime import date, datetime, timedelta, timezone
from typing import List, Optional

from backend.app.services.ingestion.sources import news_policy
from backend.app.services.ingestion.sources.news_transport import TechmemeTransport

logger = logging.getLogger(__name__)

TECHMEME_RSS_URL = "https://www.techmeme.com/feed.xml"
TECHMEME_HOME_URL = "https://www.techmeme.com/"
_RSS_MAX_ITEMS = news_policy.RSS_MAX_ITEMS

_parse_entry_date = news_policy.parse_entry_date
_clean_html = news_policy.clean_html
_within_period = news_policy.within_period


def _fetch_rss_articles(
    limit: int,
    period: str,
    anchor: date,
    source_channel: str,
) -> List[dict]:
    """从 Techmeme RSS 采集文章。"""
    try:
        feed = news_policy.parse_rss(TechmemeTransport().fetch_rss())
    except ImportError:
        logger.error("[News] feedparser 未安装，请执行: pip install feedparser")
        return []
    except Exception as exc:
        logger.error("[News] 无法获取或解析 Techmeme RSS: %s", exc)
        return []

    logger.info(
        "[News] Techmeme RSS 返回 %d 条条目（官方上限约 %d 条）",
        len(feed.entries),
        _RSS_MAX_ITEMS,
    )
    return news_policy.project_rss_entries(
        feed.entries,
        limit=limit,
        period=period,
        anchor=anchor,
        source_channel=source_channel,
    )


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
    try:
        html = TechmemeTransport().fetch_homepage()
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

    results = news_policy.project_homepage_matches(
        news_policy.extract_homepage_matches(html),
        limit=limit,
        period=period,
        anchor=anchor,
        source_channel=source_channel,
        existing_urls=existing_urls,
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
