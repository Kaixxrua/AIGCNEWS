from __future__ import annotations

import json
import logging
from typing import Any
from urllib.parse import parse_qs, urlparse

from backend.app.services.wechat.errors import (
    WeChatLoginFailed,
    WeChatSessionExpired,
    WeChatUpstreamError,
)

logger = logging.getLogger(__name__)

# WeChat QR polling status codes observed in the reference exporter.
QR_STATUS_WAITING = 0
QR_STATUS_CONFIRMED = 1
QR_STATUS_EXPIRED_2 = 2
QR_STATUS_EXPIRED_3 = 3
QR_STATUS_SCANNED = 4
QR_STATUS_NO_BOUND_EMAIL = 5
QR_STATUS_SCANNED_6 = 6


def extract_token_from_redirect_url(redirect_url: str) -> str | None:
    """Extract the WeChat token query param from a redirect URL path."""
    if not redirect_url:
        return None
    parsed = urlparse(redirect_url)
    values = parse_qs(parsed.query).get("token")
    return values[0] if values else None


def _clean_base_resp(body: dict[str, Any]) -> dict[str, Any]:
    return body.get("base_resp") or {}


def check_base_resp_or_raise(body: dict[str, Any]) -> None:
    """Validate the standard WeChat JSON envelope and raise mapped errors."""
    base_resp = _clean_base_resp(body)
    ret = base_resp.get("ret")

    if ret in (0, "0"):
        return

    if ret in (200003, "200003"):
        raise WeChatSessionExpired()

    if ret in (1000, "1000"):
        raise WeChatLoginFailed("扫码确认超时或微信系统繁忙，请重试")

    logger.warning("WeChat upstream error: ret=%s", ret)
    raise WeChatUpstreamError(f"微信错误 {ret}")


def map_scan_status(
    body: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    """Map the scanloginqrcode ask response to an internal status and metadata.

    Returns:
        (status, metadata) where status is one of:
        waiting_scan, scanned_waiting_confirmation, confirmed,
        qr_expired, failed.
    """
    check_base_resp_or_raise(body)

    status = body.get("status")
    acct_size = body.get("acct_size") or 0
    binduin = body.get("binduin") or ""
    metadata: dict[str, Any] = {"upstream_status": status, "acct_size": acct_size}

    if status == QR_STATUS_WAITING:
        return "waiting_scan", metadata

    if status == QR_STATUS_CONFIRMED:
        return "confirmed", metadata

    if status in (QR_STATUS_EXPIRED_2, QR_STATUS_EXPIRED_3):
        return "qr_expired", metadata

    if status in (QR_STATUS_SCANNED, QR_STATUS_SCANNED_6):
        if acct_size >= 1:
            return "scanned_waiting_confirmation", {"binduin": binduin, **metadata}
        return "failed", {"reason": "没有可登录账号", **metadata}

    if status == QR_STATUS_NO_BOUND_EMAIL:
        return "failed", {"reason": "该账号尚未绑定邮箱", **metadata}

    logger.warning("Unknown WeChat QR status: %s", status)
    return "failed", {"reason": "未知扫码状态", **metadata}


def parse_biz_login_response(
    body: dict[str, Any],
) -> tuple[str | None, dict[str, Any]]:
    """Parse the bizlogin login response and return (token, redirect_info)."""
    check_base_resp_or_raise(body)

    redirect_url = body.get("redirect_url") or ""
    token = extract_token_from_redirect_url(redirect_url)
    if not token:
        logger.warning("bizlogin succeeded but no token in redirect_url")
        raise WeChatLoginFailed("登录成功但未获取到 token")
    return token, {"redirect_url": redirect_url}


def decode_publish_page(raw: str | None) -> dict[str, Any]:
    """Decode the stringified publish_page JSON envelope."""
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.warning("Failed to decode publish_page JSON: %s", exc)
        raise WeChatUpstreamError("文章列表格式异常") from exc


def decode_publish_info(raw: str | None) -> dict[str, Any]:
    """Decode the stringified publish_info JSON inside a publish list item."""
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.warning("Failed to decode publish_info JSON: %s", exc)
        raise WeChatUpstreamError("文章详情格式异常") from exc


def parse_appmsg_publish_response(body: dict[str, Any]) -> tuple[list[dict[str, Any]], int]:
    """Return (articles, message_count) from an appmsgpublish response.

    *articles* is a flattened list of article dicts enriched with message-level
    ids. *message_count* is the number of publish messages for which the head
    article (itemidx == 1) was returned, used to advance pagination.
    """
    check_base_resp_or_raise(body)

    publish_page = decode_publish_page(body.get("publish_page"))
    publish_list = publish_page.get("publish_list") or []

    articles: list[dict[str, Any]] = []
    message_count = 0

    for item in publish_list:
        publish_info = decode_publish_info(item.get("publish_info"))
        msgid = publish_info.get("msgid") or publish_info.get("appmsgid")
        appmsgex = publish_info.get("appmsgex") or []
        if appmsgex:
            message_count += 1
        for article in appmsgex:
            enriched = dict(article)
            enriched["msgid"] = msgid
            articles.append(enriched)

    return articles, message_count


def parse_search_biz_response(body: dict[str, Any]) -> tuple[list[dict[str, Any]], int]:
    """Return (accounts, total) from a searchbiz response."""
    check_base_resp_or_raise(body)

    total = body.get("total") or 0
    accounts = body.get("list") or []
    return accounts, int(total)


def build_stable_article_key(article: dict[str, Any]) -> str:
    """Build the most stable identifier available for an article.

    Preference: appmsgid + itemidx > link > aid.
    """
    appmsgid = article.get("appmsgid")
    itemidx = article.get("itemidx")
    if appmsgid is not None and itemidx is not None:
        return f"{appmsgid}-{itemidx}"
    link = article.get("link") or article.get("url")
    if link:
        return link.strip()
    aid = article.get("aid")
    if aid:
        return str(aid).strip()
    title = article.get("title") or ""
    create_time = article.get("create_time") or ""
    return f"{create_time}:{title.strip()}"


def normalize_article_metadata(article: dict[str, Any]) -> dict[str, Any]:
    """Convert a raw WeChat AppMsgEx article into the repository payload shape."""
    create_time = article.get("create_time")
    published_at: str | None = None
    if create_time:
        from datetime import datetime, timezone

        try:
            published_at = datetime.fromtimestamp(int(create_time), tz=timezone.utc).isoformat()
        except (TypeError, ValueError):
            published_at = None

    return {
        "stable_article_key": build_stable_article_key(article),
        "message_id": str(article.get("msgid") or article.get("appmsgid") or ""),
        "itemidx": int(article.get("itemidx") or 1),
        "title": str(article.get("title") or "").strip(),
        "digest": str(article.get("digest") or "").strip(),
        "author": str(article.get("author") or "").strip(),
        "article_url": str(article.get("link") or article.get("url") or "").strip(),
        "cover_url": str(article.get("cover") or "").strip(),
        "source_url": str(article.get("source_url") or "").strip(),
        "published_at": published_at,
        "raw_metadata": article,
    }
