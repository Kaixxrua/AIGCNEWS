from __future__ import annotations

"""Product Hunt 数据源：通过主页 Apollo SSR 数据获取热门产品（含真实投票数）。

原理：
  PH 主页使用 Apollo SSR Transport 将今日/近期推荐产品列表嵌入 HTML。
  通过 curl_cffi（impersonate Chrome）绕过 Cloudflare，解析内嵌的
  JSON 数据获取产品名称、tagline、投票数（launchDayScore）等信息。

  URL:  https://www.producthunt.com/
  数据: window[Symbol.for("ApolloSSRDataTransport")] 中的 homefeed.items

时间约定：
  - PH 以 PDT/PST（UTC-7/UTC-8）为基准发布日期
  - published_date 使用 UTC+8（CST）的爬取时间，保证在中国时区下日期匹配
  - featuredAt 原始值保留在 extra 字段中以备参考

source_channel = producthunt_daily_html / producthunt_weekly_html / producthunt_monthly_html
"""

import asyncio
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx

from backend.app.services.ingestion import (
    producthunt_parser,
    producthunt_projection,
    producthunt_transport,
)

logger = logging.getLogger(__name__)

PH_HOME_URL = "https://www.producthunt.com/"
_CST = timezone(timedelta(hours=8))

# 每个周期最多允许往前追溯多少天（PST 比 CST 早约 15-16 小时）
_PERIOD_DAYS: Dict[str, int] = {"daily": 2, "weekly": 7, "monthly": 30}

# 重试配置
_MAX_RETRIES = 3
_RETRY_DELAY = 2.0  # 秒

# 更逼真的浏览器 Headers（用于 httpx fallback）
_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,image/apng,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}


# ---------------------------------------------------------------------------
# 内部工具
# ---------------------------------------------------------------------------


def _today_cst() -> date:
    """返回 UTC+8 当前日期。"""
    return datetime.now(_CST).date()


def _parse_featured_at(feat_str: str) -> Optional[date]:
    """解析 featuredAt 字符串（带时区偏移）为 date 对象。"""
    if not feat_str:
        return None
    try:
        dt = datetime.fromisoformat(feat_str)
        return dt.date()
    except ValueError:
        pass
    try:
        return date.fromisoformat(feat_str[:10])
    except ValueError:
        return None


def _within_period(feat_date: Optional[date], period: str, anchor: date) -> bool:
    """判断产品的 featuredAt 日期是否在指定周期窗口内。

    PH 以 PST/PDT 为准，featured 日期比 CST anchor 可能早 1 天，
    因此 end 放宽到 anchor + 1 天。
    """
    if feat_date is None:
        return True
    days = _PERIOD_DAYS.get(period, 2)
    start = anchor - timedelta(days=days)
    end = anchor + timedelta(days=1)
    return start <= feat_date <= end


# ---------------------------------------------------------------------------
# 核心抓取（带重试 + fallback）
# ---------------------------------------------------------------------------


# curl_cffi impersonate 候选列表（不同版本应对不同 Cloudflare 指纹检测）
_IMPERSONATE_OPTIONS = ["chrome124", "chrome120", "chrome116", "chrome110", "chrome107"]


async def _fetch_html_curl_cffi(url: str) -> Optional[str]:
    """兼容旧 monkeypatch 点，转发到抽取后的 curl_cffi transport。"""
    return await producthunt_transport.fetch_html_curl_cffi(url)


async def _fetch_html_httpx(url: str) -> Optional[str]:
    """兼容旧 monkeypatch 点，转发到抽取后的 httpx transport。"""
    return await producthunt_transport.fetch_html_httpx(url)


async def _fetch_html(url: str) -> str:
    """抓取页面 HTML，带重试和 fallback 机制。"""
    html = await _fetch_html_curl_cffi(url)
    if html:
        return html

    logger.warning("[ProductHunt] curl_cffi 全部失败，尝试 httpx fallback...")

    html = await _fetch_html_httpx(url)
    if html:
        return html

    logger.error(
        "[ProductHunt] 所有抓取方式均失败（curl_cffi + httpx），共尝试 %d 次。"
        "可能原因：1) Cloudflare/403 拦截 2) 网络问题 3) PH 页面结构变更",
        _MAX_RETRIES * 2,
    )
    return ""


def _extract_posts_from_html(html: str) -> List[Dict[str, Any]]:
    """兼容旧 monkeypatch 点，转发到抽取后的 Apollo parser。"""
    return producthunt_parser.extract_posts_from_html(html)


# ---------------------------------------------------------------------------
# PH API v2 通道（首选，不受 Cloudflare 限制）
# ---------------------------------------------------------------------------

_PH_API_URL = "https://api.producthunt.com/v2/api/graphql"

_PH_POSTS_QUERY = """
query GetPosts($first: Int!, $order: PostsOrder!) {
    posts(first: $first, order: $order) {
        edges {
            node {
                id
                name
                tagline
                slug
                url
                votesCount
                commentsCount
                featuredAt
                topics {
                    edges {
                        node {
                            name
                        }
                    }
                }
            }
        }
    }
}
"""


async def _fetch_via_api(
    limit: int,
    period: str,
    anchor: date,
    source_channel: str,
    crawl_date_str: str,
) -> Optional[List[Dict[str, Any]]]:
    """兼容旧 monkeypatch 点，协调 API edges transport 与统一投影。"""
    edges = await producthunt_transport.fetch_api_edges(limit)
    if not edges:
        return None
    results = producthunt_projection.project_api_items(
        edges,
        period,
        anchor,
        source_channel,
        crawl_date_str,
    )
    logger.info(
        "[ProductHunt] API v2 获取 %d 条产品（period=%s, anchor=%s）",
        len(results or []),
        period,
        anchor,
    )
    return results


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------


async def fetch_producthunt_products_async(
    limit: int = 20,
    period: str = "daily",
    target_date: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """获取 Product Hunt 热门产品列表（含真实投票数）。

    三通道策略（按优先级）：
      1. PH API v2（需要 PRODUCTHUNT_API_TOKEN，不受 Cloudflare 限制）
      2. curl_cffi + Apollo SSR 解析（绕过 Cloudflare）
      3. httpx + 浏览器 Headers（最后手段）

    Args:
        limit: 最多返回条数
        period: daily / weekly / monthly
        target_date: 可选 YYYY-MM-DD（不传默认 UTC+8 今天）

    Returns:
        标准化 product dict 列表，兼容 pipeline._to_documents() 格式。
    """
    period = (period or "daily").lower().strip()

    # anchor 日期（UTC+8）
    anchor = _today_cst()
    if target_date:
        try:
            anchor = date.fromisoformat(target_date)
        except ValueError:
            logger.warning("[ProductHunt] target_date 解析失败: %s", target_date)

    # 爬取时间（UTC+8）
    crawl_dt = datetime.now(_CST)
    crawl_date_str = crawl_dt.date().isoformat()

    source_channel = f"producthunt_{period}_html"

    logger.info("[ProductHunt] 开始抓取 period=%s anchor=%s", period, anchor)

    # ── 通道 1: PH API v2（首选，需要 token） ──
    api_results = await _fetch_via_api(
        limit,
        period,
        anchor,
        source_channel,
        crawl_date_str,
    )
    if api_results:
        logger.info("[ProductHunt] API v2 通道成功，返回 %d 条", len(api_results))
        return api_results

    logger.info("[ProductHunt] API v2 不可用，回退到 HTML 解析...")

    # ── 通道 2+3: HTML 解析（curl_cffi + httpx fallback） ──
    html = await _fetch_html(PH_HOME_URL)
    if not html:
        logger.error(
            "[ProductHunt] 页面抓取完全失败，返回空列表。"
            "建议配置 PRODUCTHUNT_API_TOKEN 以绕过 Cloudflare。"
            "申请地址：https://www.producthunt.com/v2/oauth/applications"
        )
        return []

    # 提取所有 Post
    all_posts = _extract_posts_from_html(html)
    if not all_posts:
        logger.error(
            "[ProductHunt] 未提取到任何 Post 对象，返回空列表。"
            "页面长度=%d，请检查页面内容是否为 Cloudflare 挑战页面。",
            len(html),
        )
        return []

    # 按周期筛选 + 构造标准字段
    results: List[Dict[str, Any]] = []
    for post in all_posts:
        if len(results) >= limit:
            break

        featured_at_str = post.get("featuredAt", "")
        feat_date = _parse_featured_at(featured_at_str)

        if not _within_period(feat_date, period, anchor):
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

        daily_rank = str(post.get("dailyRank") or "")
        weekly_rank = str(post.get("weeklyRank") or "")
        monthly_rank = str(post.get("monthlyRank") or "")

        # 提取话题标签
        topics: List[str] = []
        topics_data = post.get("topics") or {}
        if isinstance(topics_data, dict):
            for edge in topics_data.get("edges", []):
                node = edge.get("node", {})
                if isinstance(node, dict) and node.get("name"):
                    topics.append(node["name"])

        # published_date 使用 UTC+8 爬取日期，保证在中国时区下日期匹配
        # featuredAt 保留在 abstract 补充信息中
        feat_date_str = feat_date.isoformat() if feat_date else crawl_date_str

        # 如果 feat_date 是昨天（PST），published_date 用今天（CST）
        # 如果 feat_date 更早（weekly/monthly），保留原始日期
        if period == "daily" and feat_date and feat_date < anchor:
            pub_date = anchor.isoformat()
        else:
            pub_date = feat_date_str or crawl_date_str

        abstract = tagline
        if topics:
            abstract = f"{tagline} [{', '.join(topics[:3])}]"

        item: Dict[str, Any] = {
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
            # 保留原始字段，供调试
            "featured_at": featured_at_str,
            "daily_rank": daily_rank,
            "weekly_rank": weekly_rank,
            "monthly_rank": monthly_rank,
        }
        results.append(item)

    logger.info(
        "[ProductHunt] period=%s anchor=%s 筛选出 %d 条产品（共 %d Post）",
        period,
        anchor,
        len(results),
        len(all_posts),
    )

    # 如果当日无数据，放宽为最近数据（保证页面不空）
    if not results:
        logger.warning(
            "[ProductHunt] period=%s 无符合条件的产品，使用所有抓取数据（最多%d条）",
            period,
            limit,
        )
        for post in all_posts[:limit]:
            name = (post.get("name") or "").strip()
            tagline = (post.get("tagline") or "").strip()
            if not name:
                continue
            slug = post.get("slug", "")
            url = f"https://www.producthunt.com/posts/{slug}" if slug else ""
            launch_score = int(post.get("launchDayScore") or 0)
            latest_score = int(post.get("latestScore") or 0)
            votes = max(launch_score, latest_score)
            topics = []
            topics_data = post.get("topics") or {}
            if isinstance(topics_data, dict):
                for edge in topics_data.get("edges", []):
                    node = edge.get("node", {})
                    if isinstance(node, dict) and node.get("name"):
                        topics.append(node["name"])
            item = {
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
            results.append(item)
        logger.info("[ProductHunt] 放宽后返回 %d 条", len(results))

    return results


# ── 同步兼容包装器（供旧调用方使用） ──────────────────────────────────────────


def fetch_producthunt_products(
    limit: int = 20,
    period: str = "daily",
    target_date: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """同步包装器：自动检测事件循环，选择合适的调用方式。"""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(
                asyncio.run,
                fetch_producthunt_products_async(
                    limit=limit,
                    period=period,
                    target_date=target_date,
                ),
            )
            return future.result(timeout=120)

    return asyncio.run(
        fetch_producthunt_products_async(
            limit=limit,
            period=period,
            target_date=target_date,
        )
    )
