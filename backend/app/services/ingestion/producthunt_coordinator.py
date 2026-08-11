from __future__ import annotations

import logging
from datetime import date
from typing import Any, Awaitable, Callable, Dict, List, Optional

from backend.app.services.ingestion import producthunt_policy
from backend.app.services.ingestion.producthunt_parser import extract_posts_from_html
from backend.app.services.ingestion.producthunt_projection import (
    project_api_items,
    project_html_items,
)
from backend.app.services.ingestion.producthunt_transport import (
    PH_HOME_URL,
    fetch_api_edges,
    fetch_html,
)

logger = logging.getLogger(__name__)

ApiEdgesTransport = Callable[
    [int, Optional[date]], Awaitable[Optional[List[Dict[str, Any]]]]
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
        edges = await api_transport(limit, anchor)
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
        # 开榜窗口退化样本守卫：整批 0 票时不再回落 HTML——HTML 读同一
        # 块新榜只会拿到同样的 0 票，直接诚实回空。
        if producthunt_policy.all_zero_votes(api_results):
            logger.warning(
                "[ProductHunt] API v2 返回 %d 条但票数全 0（period=%s anchor=%s，"
                "新榜日开榜窗口退化样本），本轮回空保留上一片好数据",
                len(api_results),
                normalized_period,
                anchor,
            )
            return []
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

    # PR7：删除 relaxed 宽松兜底——严格过滤为空的轮次诚实回空，不再把
    # 窗口外/无 featuredAt 的条目伪装成当期榜单静默填版。空结果由
    # 管道按零入库处理（保留上一片好数据，快照日期如实反映陈旧度）。
    if not results:
        logger.warning(
            "[ProductHunt] period=%s anchor=%s 严格过滤后 0 条，本轮回空",
            normalized_period,
            anchor,
        )
        return results

    # 开榜窗口退化样本守卫（同 PR7 诚实回空语义）：整批票数全 0 说明
    # 新榜日刚开榜、排名无信息量，写库会把当日快照污染成全 0 票。
    if producthunt_policy.all_zero_votes(results):
        logger.warning(
            "[ProductHunt] period=%s anchor=%s %d 条票数全 0"
            "（新榜日开榜窗口退化样本），本轮回空保留上一片好数据",
            normalized_period,
            anchor,
            len(results),
        )
        return []

    return results
