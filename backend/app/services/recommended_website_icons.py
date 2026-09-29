"""Best-effort logo for a curated website: the site's own icon, kept as a public site asset.

A website is only fetched when an administrator saves it. The page and the icon go through the tool website
fetcher (every hop SSRF-validated and pinned, bounded size, proxy fallback); the icon is decoded and
re-encoded as a small WebP before it is stored, so visitors never load third-party hosts and never receive
the original bytes. SVG icons are skipped because the public asset tree only serves raster images. Any
failure yields an empty string and the page shows the site's monogram instead.
"""

from __future__ import annotations

import logging
from urllib.parse import urlsplit, urlunsplit

from backend.app.services.ingestion.github_project_logos import sanitize_image
from backend.app.services.ingestion.tool_website_fetcher import (
    download_tool_website_image,
    fetch_tool_website_metadata,
)
from backend.app.services.site_assets import store_site_image

logger = logging.getLogger(__name__)


def _favicon_url(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, "/favicon.ico", "", ""))


def _icon_candidates(url: str) -> list[str]:
    candidates: list[str] = []
    try:
        metadata = fetch_tool_website_metadata(url)
        # logo_url is the page's apple-touch-icon, icon or mask-icon link, else its /favicon.ico; unlike
        # image_url it never falls back to the og:image banner.
        candidates.append(str(metadata.raw_metadata.get("logo_url") or ""))
        candidates.append(_favicon_url(metadata.canonical_url))
    except Exception as error:  # a logo is decoration; the save must not fail over it
        logger.info("recommended website page fetch failed for %s: %s", url, error)
    candidates.append(_favicon_url(url))
    return list(dict.fromkeys(candidate for candidate in candidates if candidate))


def fetch_recommended_website_icon(url: str) -> str:
    """Return the site-asset URL of the website's icon, or "" when none could be fetched safely."""
    for candidate in _icon_candidates(url):
        try:
            image, mime_type = sanitize_image(download_tool_website_image(candidate))
            if mime_type != "image/webp":
                continue
            return store_site_image(image, mime_type)
        except Exception as error:  # try the next candidate, then fall back to the monogram
            logger.info("recommended website icon %s skipped: %s", candidate, error)
    return ""
