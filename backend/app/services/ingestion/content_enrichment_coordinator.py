from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any, Dict, Optional

from backend.app.services.ingestion.content_enrichment_policy import (
    ContentEnrichmentPolicy,
    compose_huggingface_content,
    compose_producthunt_content,
    compose_x_content,
    select_github_content,
    select_hackernews_content,
    select_news_content,
)
from backend.app.services.ingestion.content_fetch_port import (
    GitHubReadmeFetcher,
    PageContentFetcher,
)

logger = logging.getLogger(__name__)

PageTextFetch = Callable[[str], Awaitable[str]]
GitHubReadmeFetch = Callable[[str], Awaitable[str]]


def apply_content_policy(
    paper: Dict[str, Any],
    policy: ContentEnrichmentPolicy,
) -> Dict[str, Any]:
    """Write a pure policy result back while preserving in-place mutation."""
    paper["full_text"] = policy.full_text
    if policy.pdf_pending is not None:
        paper["pdf_pending"] = policy.pdf_pending
    return paper


def enrich_huggingface(paper: Dict[str, Any]) -> Dict[str, Any]:
    """Compose Hugging Face model content without network access."""
    policy = compose_huggingface_content(paper)
    apply_content_policy(paper, policy)

    title = paper.get("title", "")
    logger.debug(
        "[Enricher][HuggingFace] 摘要入库: %s (%d chars)",
        title[:50],
        len(policy.full_text),
    )
    return paper


async def enrich_github(
    paper: Dict[str, Any],
    *,
    readme_fetcher: Optional[GitHubReadmeFetcher] = None,
    fetch_readme: GitHubReadmeFetch,
) -> Dict[str, Any]:
    """Select existing GitHub content or fetch and compose a README."""
    policy = select_github_content(paper)
    if policy.fetch_github_readme:
        full_name = policy.fetch_github_readme
        logger.info("[Enricher][GitHub] 补抓 README: %s", full_name)
        readme = (
            await readme_fetcher.fetch(full_name)
            if readme_fetcher is not None
            else await fetch_readme(full_name)
        )
        policy = select_github_content(paper, readme)

    return apply_content_policy(paper, policy)


async def enrich_news(
    paper: Dict[str, Any],
    *,
    page_fetcher: Optional[PageContentFetcher] = None,
    fetch_page: PageTextFetch,
) -> Dict[str, Any]:
    """Fetch and select News page content with the existing fallbacks."""
    policy = select_news_content(paper)
    if policy.fetch_url:
        url = policy.fetch_url
        logger.info("[Enricher][News] 抓取详情页: %s", url[:80])
        page_text = (
            await page_fetcher.fetch(url)
            if page_fetcher is not None
            else await fetch_page(url)
        )
        policy = select_news_content(paper, page_text)

    return apply_content_policy(paper, policy)


def enrich_producthunt(paper: Dict[str, Any]) -> Dict[str, Any]:
    """Compose Product Hunt content without an additional fetch."""
    return apply_content_policy(paper, compose_producthunt_content(paper))


def enrich_x(paper: Dict[str, Any]) -> Dict[str, Any]:
    """Compose X tweet content without an additional fetch."""
    return apply_content_policy(paper, compose_x_content(paper))


async def enrich_hackernews(
    paper: Dict[str, Any],
    *,
    page_fetcher: Optional[PageContentFetcher] = None,
    fetch_page: PageTextFetch,
) -> Dict[str, Any]:
    """Fetch external Hacker News content while preserving story fallbacks."""
    policy = select_hackernews_content(paper)
    if policy.fetch_url:
        url = policy.fetch_url
        logger.info("[Enricher][HackerNews] 抓取外链详情页: %s", url[:80])
        page_text = (
            await page_fetcher.fetch(url)
            if page_fetcher is not None
            else await fetch_page(url)
        )
        policy = select_hackernews_content(paper, page_text)

    return apply_content_policy(paper, policy)
