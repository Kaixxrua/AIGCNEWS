from __future__ import annotations

"""Product Hunt ingestion compatibility facade."""

import asyncio
from datetime import date
from typing import Any, Dict, List, Optional

from backend.app.services.ingestion import (
    producthunt_coordinator,
    producthunt_parser,
    producthunt_policy,
    producthunt_projection,
    producthunt_transport,
)


def _resolve_anchor(target_date: Optional[str]) -> date:
    """Forward the legacy anchor-policy entry point."""
    return producthunt_policy.resolve_anchor(target_date)


def _parse_featured_at(feat_str: str) -> Optional[date]:
    """Forward the legacy featured-date parser entry point."""
    return producthunt_policy.parse_featured_at(feat_str)


def _within_period(feat_date: Optional[date], period: str, anchor: date) -> bool:
    """Forward the legacy period-policy entry point."""
    return producthunt_policy.within_period(feat_date, period, anchor)


async def _fetch_html_curl_cffi(url: str) -> Optional[str]:
    """Forward the legacy curl_cffi transport entry point."""
    return await producthunt_transport.fetch_html_curl_cffi(url)


async def _fetch_html_httpx(url: str) -> Optional[str]:
    """Forward the legacy httpx transport entry point."""
    return await producthunt_transport.fetch_html_httpx(url)


async def _fetch_html(url: str) -> str:
    """Forward the legacy HTML transport entry point."""
    return await producthunt_transport.fetch_html(url)


def _extract_posts_from_html(html: str) -> List[Dict[str, Any]]:
    """Forward the legacy Apollo parser entry point."""
    return producthunt_parser.extract_posts_from_html(html)


async def _fetch_via_api(
    limit: int,
    period: str,
    anchor: date,
    source_channel: str,
    crawl_date_str: str,
) -> Optional[List[Dict[str, Any]]]:
    """Preserve the legacy projected API-channel entry point."""
    edges = await producthunt_transport.fetch_api_edges(limit)
    if not edges:
        return None
    return producthunt_projection.project_api_items(
        edges,
        period,
        anchor,
        source_channel,
        crawl_date_str,
    )


async def fetch_producthunt_products_async(
    limit: int = 20,
    period: str = "daily",
    target_date: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Fetch Product Hunt products through the layered coordinator."""
    return await producthunt_coordinator.fetch_producthunt_products(
        limit=limit,
        period=period,
        target_date=target_date,
    )


def fetch_producthunt_products(
    limit: int = 20,
    period: str = "daily",
    target_date: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Synchronously invoke the async Product Hunt compatibility entry point."""
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
