"""Parsers for the Sogou WeChat public index (weixin.sogou.com).

Pure functions over HTML strings; no I/O. Fixtures captured from real
responses live in backend/tests/fixtures/wechat_sogou/.
"""

from __future__ import annotations

import html as html_lib
import logging
import re
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

_ITEM_RE = re.compile(
    r'<li id="sogou_vr_11002601_box_\d+"[^>]*>[\s\S]*?</li>',
)
_TITLE_LINK_RE = re.compile(r'<h3>\s*<a[^>]*href="(?P<href>[^"]+)"[^>]*>(?P<title>[\s\S]*?)</a>')
_SUMMARY_RE = re.compile(r'<p class="txt-info"[^>]*>(?P<summary>[\s\S]*?)</p>')
_ACCOUNT_RE = re.compile(r'<span class="all-time-y2">(?P<account>[\s\S]*?)</span>')
_TIME_RE = re.compile(r"timeConvert\('(?P<ts>\d+)'\)")
_COVER_RE = re.compile(r'<img src="(?P<src>[^"]+)"')
_SIGNED_URL_PART_RE = re.compile(r"url \+= '(?P<part>[^']*)';")
# Real mp article pages emit fallback chains: var mid = "224..." || "" || "";
# The value capture stops at the first closing quote, so no semicolon anchor.
_VAR_RE_TEMPLATE = r'var {name} = ["\'](?P<value>[^"\']*)["\']'


def _strip_markup(fragment: str) -> str:
    """Remove Sogou highlight markers (<em><!--red_beg-->...) and tags."""
    fragment = re.sub(r"<!--.*?-->", "", fragment)
    fragment = re.sub(r"<[^>]+>", "", fragment)
    return html_lib.unescape(fragment).strip()


def is_antispider_content(body: str) -> bool:
    return "antispider" in body or "验证码" in body


def parse_article_search_page(body: str) -> list[dict[str, Any]]:
    """Parse a type=2 article search results page.

    Returns one dict per result: title, summary, account_name, link_path
    (Sogou redirect, short-lived), cover_url, published_ts (unix seconds).
    """
    items: list[dict[str, Any]] = []
    for item_html in _ITEM_RE.findall(body):
        title_match = _TITLE_LINK_RE.search(item_html)
        if title_match is None:
            continue
        account_match = _ACCOUNT_RE.search(item_html)
        time_match = _TIME_RE.search(item_html)
        summary_match = _SUMMARY_RE.search(item_html)
        cover_match = _COVER_RE.search(item_html)
        items.append(
            {
                "title": _strip_markup(title_match.group("title")),
                "summary": _strip_markup(summary_match.group("summary")) if summary_match else "",
                "account_name": _strip_markup(account_match.group("account")) if account_match else "",
                "link_path": html_lib.unescape(title_match.group("href")),
                "cover_url": html_lib.unescape(cover_match.group("src")) if cover_match else "",
                "published_ts": int(time_match.group("ts")) if time_match else None,
            }
        )
    return items


def extract_signed_url_from_redirect(body: str) -> str:
    """Rebuild the signed mp.weixin.qq.com URL from the redirect page JS."""
    parts = _SIGNED_URL_PART_RE.findall(body)
    url = "".join(parts)
    if not url.startswith("http"):
        raise ValueError("redirect page did not contain a signed url")
    return url


def _extract_var(body: str, name: str) -> str:
    match = re.search(_VAR_RE_TEMPLATE.format(name=re.escape(name)), body)
    return match.group("value") if match else ""


def extract_article_identity(body: str) -> dict[str, Any]:
    """Extract canonical identifiers from an mp.weixin.qq.com article page."""
    ct = _extract_var(body, "ct")
    published_at: str | None = None
    if ct.isdigit():
        published_at = datetime.fromtimestamp(int(ct), tz=timezone.utc).isoformat()
    return {
        "biz": _extract_var(body, "biz"),
        "mid": _extract_var(body, "mid"),
        "idx": _extract_var(body, "idx"),
        "sn": _extract_var(body, "sn"),
        "user_name": _extract_var(body, "user_name"),
        "nickname": html_lib.unescape(_extract_var(body, "nickname")),
        "msg_title": html_lib.unescape(_extract_var(body, "msg_title")),
        "published_at": published_at,
    }


def normalize_account_name(name: str) -> str:
    """Normalize an account name for exact-match filtering."""
    return re.sub(r"\s+", "", name).lower()


# ---------------------------------------------------------------------------
# Article body extraction & sanitization
# ---------------------------------------------------------------------------

# Structural tags found in real WeChat article bodies. Anything else is
# unwrapped (children kept) so text survives unknown markup.
_CONTENT_ALLOWED_TAGS = frozenset(
    {
        "section", "span", "p", "div", "br", "hr",
        "h1", "h2", "h3", "h4", "h5", "h6",
        "strong", "b", "em", "i", "u", "s", "blockquote",
        "ul", "ol", "li", "a", "img", "figure", "figcaption",
        "table", "thead", "tbody", "tr", "td", "th", "caption",
        "code", "pre", "sup", "sub",
    }
)
_CONTENT_DROP_TAGS = ("script", "style", "iframe", "noscript", "svg", "form", "object", "embed")
# CSS declarations matching these are removed (overlay / exfiltration
# vectors); typography declarations (font, color, margin, ...) are kept
# so the article keeps its original look.
_STYLE_FORBIDDEN_RE = re.compile(r"url\s*\(|expression|@import|behavior|javascript|position|z-index", re.I)


def _filter_style(style: str) -> str:
    kept = []
    for declaration in style.split(";"):
        declaration = declaration.strip()
        if declaration and not _STYLE_FORBIDDEN_RE.search(declaration):
            kept.append(declaration)
    return "; ".join(kept)


def _sanitize_content_node(node: Any) -> None:
    """In-place allowlist sanitization of a BeautifulSoup subtree."""
    from bs4 import Comment

    for child in list(node.descendants):
        if isinstance(child, Comment):
            child.extract()
    for tag in node.find_all(True):
        if tag.name not in _CONTENT_ALLOWED_TAGS:
            tag.unwrap()
            continue
        attrs = dict(tag.attrs)
        tag.attrs = {}
        if tag.name == "img":
            src = html_lib.unescape(str(attrs.get("data-src") or attrs.get("src") or ""))
            if src.startswith("http://") or src.startswith("https://") or src.startswith("//"):
                tag["src"] = src
            alt = str(attrs.get("alt") or "").strip()
            if alt:
                tag["alt"] = alt
        elif tag.name == "a":
            href = html_lib.unescape(str(attrs.get("href") or "")).strip()
            if href.startswith("http://") or href.startswith("https://"):
                tag["href"] = href
                tag["rel"] = "noopener noreferrer"
                tag["target"] = "_blank"
        style = _filter_style(str(attrs.get("style") or ""))
        if style:
            tag["style"] = style


def extract_article_content(body: str) -> str:
    """Extract and sanitize the article body (<div id="js_content">).

    Returns sanitized inner HTML preserving WeChat typography (inline
    styles minus dangerous declarations). Images keep their real URLs
    (data-src -> src). Empty string when the page has no body.
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(body, "html.parser")
    container = soup.find(id="js_content")
    if container is None:
        return ""
    for tag in container.find_all(_CONTENT_DROP_TAGS):
        tag.decompose()
    _sanitize_content_node(container)
    return container.decode_contents().strip()
