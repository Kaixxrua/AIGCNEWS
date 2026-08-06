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
                "cover_url": cover_match.group("src") if cover_match else "",
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
