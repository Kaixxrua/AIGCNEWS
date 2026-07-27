from __future__ import annotations

import logging
from datetime import date
from typing import Any, Awaitable, Callable, Dict, List, Optional

from backend.app.services.ingestion import producthunt_policy
from backend.app.services.ingestion.producthunt_parser import extract_posts_from_html
from backend.app.services.ingestion.producthunt_projection import (
    project_api_items,
    project_html_items,
    project_relaxed_html_items,
)
from backend.app.services.ingestion.producthunt_transport import (
    PH_HOME_URL,
    fetch_api_edges,
    fetch_html,
)

logger = logging.getLogger(__name__)

ApiEdgesTransport = Callable[
    [int], Awaitable[Optional[List[Dict[str, Any]]]]
]
HtmlTransport = Callable[[str], Awaitable[str]]
ApolloParser = Callable[[str], List[Dict[str, Any]]]
PeriodPolicy = Callable[[str], str]
AnchorPolicy = Callable[[Optional[str]], date]
CrawlDatePolicy = Callable[[], str]
ApiProjection = Callable[
    [List[Dict[str, Any]], str, date, str, str],
    Optional[List[Dict[str, Any]]],
]
ApiChannel = Callable[
    [int, str, date, str, str],
    Awaitable[Optional[List[Dict[str, Any]]]],
]
HtmlProjection = Callable[
    [List[Dict[str, Any]], int, str, date, str, str],
    List[Dict[str, Any]],
]
RelaxedHtmlProjection = Callable[
    [List[Dict[str, Any]], int, str, str, str],
    List[Dict[str, Any]],
]


async def fetch_producthunt_products(
    limit: int = 20,
    period: str = "daily",
    target_date: Optional[str] = None,
    *,
    normalize_period: PeriodPolicy = producthunt_policy.normalize_period,
    resolve_anchor: AnchorPolicy = producthunt_policy.resolve_anchor,
    crawl_date: CrawlDatePolicy = producthunt_policy.crawl_date_cst,
    api_transport: ApiEdgesTransport = fetch_api_edges,
    api_channel: Optional[ApiChannel] = None,
    html_transport: HtmlTransport = fetch_html,
    apollo_parser: ApolloParser = extract_posts_from_html,
    api_projection: ApiProjection = project_api_items,
    html_projection: HtmlProjection = project_html_items,
    relaxed_html_projection: RelaxedHtmlProjection = project_relaxed_html_items,
) -> List[Dict[str, Any]]:
    """Coordinate Product Hunt transports, parsing, policy, and projections."""
    normalized_period = normalize_period(period)
    anchor = resolve_anchor(target_date)
    crawl_date_str = crawl_date()
    source_channel = f"producthunt_{normalized_period}_html"

    logger.info(
        "[ProductHunt] 开始抓取 period=%s anchor=%s", normalized_period, anchor
    )

    if api_channel is not None:
        api_results = await api_channel(
            limit,
            normalized_period,
            anchor,
            source_channel,
            crawl_date_str,
        )
    else:
        edges = await api_transport(limit)
        api_results = (
            api_projection(
                edges,
                normalized_period,
                anchor,
                source_channel,
                crawl_date_str,
            )
            if edges
            else None
        )
    if api_results:
        logger.info("[ProductHunt] API v2 通道成功，返回 %d 条", len(api_results))
        return api_results

    logger.info("[ProductHunt] API v2 不可用，回退到 HTML 解析...")
    html = await html_transport(PH_HOME_URL)
    if not html:
        logger.error(
            "[ProductHunt] 页面抓取完全失败，返回空列表。"
            "建议配置 PRODUCTHUNT_API_TOKEN 以绕过 Cloudflare。"
            "申请地址：https://www.producthunt.com/v2/oauth/applications"
        )
        return []

    posts = apollo_parser(html)
    if not posts:
        logger.error(
            "[ProductHunt] 未提取到任何 Post 对象，返回空列表。"
            "页面长度=%d，请检查页面内容是否为 Cloudflare 挑战页面。",
            len(html),
        )
        return []

    results = html_projection(
        posts,
        limit,
        normalized_period,
        anchor,
        source_channel,
        crawl_date_str,
    )
    logger.info(
        "[ProductHunt] period=%s anchor=%s 筛选出 %d 条产品（共 %d Post）",
        normalized_period,
        anchor,
        len(results),
        len(posts),
    )

    if not results:
        logger.warning(
            "[ProductHunt] period=%s 无符合条件的产品，使用所有抓取数据（最多%d条）",
            normalized_period,
            limit,
        )
        results = relaxed_html_projection(
            posts,
            limit,
            normalized_period,
            source_channel,
            crawl_date_str,
        )
        logger.info("[ProductHunt] 放宽后返回 %d 条", len(results))

    return results
