from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

PH_HOME_URL = "https://www.producthunt.com/"
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

_MAX_RETRIES = 3
_RETRY_DELAY = 2.0
_IMPERSONATE_OPTIONS = ["chrome124", "chrome120", "chrome116", "chrome110", "chrome107"]
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


async def fetch_html_curl_cffi(url: str) -> Optional[str]:
    """使用 curl_cffi 抓取页面；成功返回 HTML，失败返回 None。"""
    try:
        from curl_cffi import requests as cf_requests  # type: ignore
    except ImportError:
        logger.warning(
            "[ProductHunt] curl_cffi 未安装，跳过此方式。安装命令: pip install curl_cffi"
        )
        return None

    for attempt in range(1, _MAX_RETRIES + 1):
        impersonate = _IMPERSONATE_OPTIONS[(attempt - 1) % len(_IMPERSONATE_OPTIONS)]
        try:
            resp = await asyncio.to_thread(
                cf_requests.get,
                url,
                impersonate=impersonate,
                timeout=30,
                allow_redirects=True,
            )
            status_code = getattr(resp, "status_code", None)
            if status_code and status_code >= 400:
                logger.warning(
                    "[ProductHunt] curl_cffi 请求返回 HTTP %d（第 %d/%d 次尝试）",
                    status_code,
                    attempt,
                    _MAX_RETRIES,
                )
                if attempt < _MAX_RETRIES:
                    await asyncio.sleep(_RETRY_DELAY * attempt)
                continue

            html = resp.text
            if html and len(html) > 1000:
                logger.info(
                    "[ProductHunt] curl_cffi 抓取成功，页面长度=%d（第 %d 次尝试）",
                    len(html),
                    attempt,
                )
                return html
            logger.warning(
                "[ProductHunt] curl_cffi 返回内容过短（%d bytes），可能被拦截（第 %d/%d 次）",
                len(html) if html else 0,
                attempt,
                _MAX_RETRIES,
            )
            if attempt < _MAX_RETRIES:
                await asyncio.sleep(_RETRY_DELAY * attempt)
        except Exception as exc:
            logger.warning(
                "[ProductHunt] curl_cffi 抓取异常（第 %d/%d 次）: %s",
                attempt,
                _MAX_RETRIES,
                exc,
            )
            if attempt < _MAX_RETRIES:
                await asyncio.sleep(_RETRY_DELAY * attempt)
    return None


async def fetch_html_httpx(url: str) -> Optional[str]:
    """使用 httpx 作为 fallback 抓取方式。"""
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            async with httpx.AsyncClient(
                timeout=30,
                follow_redirects=True,
                headers=_BROWSER_HEADERS,
                trust_env=True,
            ) as client:
                resp = await client.get(url)

            if resp.status_code >= 400:
                logger.warning(
                    "[ProductHunt] httpx fallback 返回 HTTP %d（第 %d/%d 次）",
                    resp.status_code,
                    attempt,
                    _MAX_RETRIES,
                )
                if attempt < _MAX_RETRIES:
                    await asyncio.sleep(_RETRY_DELAY * attempt)
                continue

            html = resp.text
            if html and len(html) > 1000:
                logger.info(
                    "[ProductHunt] httpx fallback 抓取成功，页面长度=%d（第 %d 次尝试）",
                    len(html),
                    attempt,
                )
                return html
            logger.warning(
                "[ProductHunt] httpx fallback 返回内容过短（%d bytes）（第 %d/%d 次）",
                len(html) if html else 0,
                attempt,
                _MAX_RETRIES,
            )
            if attempt < _MAX_RETRIES:
                await asyncio.sleep(_RETRY_DELAY * attempt)
        except Exception as exc:
            logger.warning(
                "[ProductHunt] httpx fallback 抓取异常（第 %d/%d 次）: %s",
                attempt,
                _MAX_RETRIES,
                exc,
            )
            if attempt < _MAX_RETRIES:
                await asyncio.sleep(_RETRY_DELAY * attempt)
    return None


async def fetch_html(url: str) -> str:
    """抓取页面 HTML，带重试和 fallback 机制。"""
    html = await fetch_html_curl_cffi(url)
    if html:
        return html

    logger.warning("[ProductHunt] curl_cffi 全部失败，尝试 httpx fallback...")
    html = await fetch_html_httpx(url)
    if html:
        return html

    logger.error(
        "[ProductHunt] 所有抓取方式均失败（curl_cffi + httpx），共尝试 %d 次。"
        "可能原因：1) Cloudflare/403 拦截 2) 网络问题 3) PH 页面结构变更",
        _MAX_RETRIES * 2,
    )
    return ""


async def fetch_api_edges(limit: int) -> Optional[List[Dict[str, Any]]]:
    """Fetch raw PH API v2 edges, preserving token and failure semantics."""
    try:
        from backend.app.core.config import settings

        token = settings.producthunt_api_token
    except Exception:
        token = ""

    if not token:
        logger.debug("[ProductHunt] 未配置 PRODUCTHUNT_API_TOKEN，跳过 API 通道")
        return None

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "RAG-AIGC-Agent/1.0",
    }
    variables = {"first": min(limit, 20), "order": "FEATURED_AT"}

    try:
        async with httpx.AsyncClient(
            timeout=20,
            follow_redirects=True,
            trust_env=True,
        ) as client:
            resp = await client.post(
                _PH_API_URL,
                json={"query": _PH_POSTS_QUERY, "variables": variables},
                headers=headers,
            )

            if resp.status_code == 401:
                logger.error(
                    "[ProductHunt] API v2 认证失败 (401)。"
                    "请检查 PRODUCTHUNT_API_TOKEN 是否正确。"
                    "申请地址：https://www.producthunt.com/v2/oauth/applications"
                )
                return None
            if resp.status_code >= 400:
                logger.error(
                    "[ProductHunt] API v2 请求失败 HTTP %d: %s",
                    resp.status_code,
                    resp.text[:200],
                )
                return None
            data = resp.json()
    except Exception as exc:
        logger.error("[ProductHunt] API v2 请求异常: %s", exc)
        return None

    errors = data.get("errors")
    if errors:
        logger.error("[ProductHunt] API v2 GraphQL 错误: %s", errors)
        return None

    edges = (data.get("data") or {}).get("posts", {}).get("edges", [])
    if not edges:
        logger.warning("[ProductHunt] API v2 返回 0 条产品")
        return None
    return edges
