from __future__ import annotations

"""Safe metadata fetching for admin-added AI tool websites."""

import hashlib
import json
import re
from contextlib import nullcontext
from dataclasses import dataclass
from typing import Any, Dict
from urllib.parse import urljoin, urlparse, urlunparse

import httpx
from bs4 import BeautifulSoup

from backend.app.core.config import settings
from backend.app.domain.project_taxonomy import clean_text
from backend.app.services.outbound_target_policy import (
    OutboundTargetPolicyError,
    normalize_http_url,
    pin_http_target,
    resolve_public_ips,
)

_MAX_REDIRECTS = 3
_MAX_BYTES = 1_000_000
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36 AIGC-NEWS-ToolWebsiteBot/1.0"
)
_ALLOWED_SCHEMES = {"http", "https"}
_BLOCKED_STATUS_CODES = {401, 403, 429, 503}
_REMOTE_DNS_PROXY_HOSTS = {"youtube.com", "youtu.be"}
_CHARSET_RE = re.compile(rb"charset=[\"']?([a-zA-Z0-9_\-]+)", re.IGNORECASE)
_META_CHARSET_RE = re.compile(rb"<meta[^>]+charset=[\"']?\s*([a-zA-Z0-9_\-]+)", re.IGNORECASE)
_ENCODING_ALIASES = {
    "gb2312": "gb18030",
    "gbk": "gb18030",
    "gb_2312-80": "gb18030",
    "x-gbk": "gb18030",
}


class ToolWebsiteFetchError(ValueError):
    """Raised when a tool website URL cannot be safely fetched."""


@dataclass
class ToolWebsiteMetadata:
    canonical_url: str
    normalized_url: str
    normalized_url_hash: str
    domain: str
    title: str
    description: str
    image_url: str
    raw_metadata: Dict[str, Any]
    source_fingerprint: str


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _safe_resolved_ips(hostname: str) -> list[str]:
    try:
        return list(resolve_public_ips(hostname))
    except OutboundTargetPolicyError as exc:
        if str(exc).startswith("无法解析域名"):
            raise ToolWebsiteFetchError(str(exc)) from exc
        return []


def _validate_url(raw_url: str) -> str:
    try:
        url = normalize_http_url(
            raw_url,
            allowed_ports={80, 443},
            add_default_scheme=True,
        )
        resolve_public_ips(urlparse(url).hostname or "")
        return url
    except OutboundTargetPolicyError as exc:
        message = str(exc)
        if message == "URL 端口不在允许范围内":
            message = "只允许标准 HTTP/HTTPS 端口"
        elif message == "URL 不能包含用户名或密码":
            message = "URL 不能包含用户名或密码"
        elif message == "只支持 http/https URL":
            message = "只支持 http/https URL"
        elif message == "URL 缺少域名":
            message = "不允许访问本地、内网或保留地址"
        raise ToolWebsiteFetchError(message) from exc


def _normalize_url(url: str) -> str:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower().rstrip(".")
    netloc = host
    if parsed.port and not (
        (parsed.scheme == "http" and parsed.port == 80)
        or (parsed.scheme == "https" and parsed.port == 443)
    ):
        netloc = f"{host}:{parsed.port}"
    path = parsed.path or "/"
    if path != "/":
        path = path.rstrip("/")
    return urlunparse((parsed.scheme.lower(), netloc, path, "", parsed.query, ""))


def _friendly_domain_title(domain: str) -> str:
    host = (domain or "").strip().lower().rstrip(".")
    parts = [part for part in host.split(".") if part and part not in {"www", "m", "mobile"}]
    label = parts[0] if parts else host
    known = {
        "52pojie": "吾爱破解",
        "freebuf": "FreeBuf",
        "google": "Google",
        "baidu": "百度",
        "linux": "Linux.do",
    }
    if label in known:
        return known[label]
    if label.isdigit():
        return label
    words = re.split(r"[-_]+", label)
    return " ".join(word.capitalize() for word in words if word) or host


def _default_favicon_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme.lower() not in _ALLOWED_SCHEMES or not parsed.netloc:
        return ""
    return urlunparse((parsed.scheme.lower(), parsed.netloc, "/favicon.ico", "", "", ""))


def _make_metadata(
    url: str,
    *,
    title: str,
    description: str,
    image_url: str = "",
    raw_metadata: Dict[str, Any] | None = None,
) -> ToolWebsiteMetadata:
    parsed = urlparse(url)
    domain = (parsed.hostname or "").lower().rstrip(".")
    normalized_url = _normalize_url(url)
    clean_title = clean_text(title or _friendly_domain_title(domain) or normalized_url, max_len=512)
    clean_description = clean_text(description, max_len=1024)
    metadata = raw_metadata or {}
    fingerprint_payload = json.dumps(
        {
            "url": normalized_url,
            "domain": domain,
            "title": clean_title,
            "description": clean_description,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return ToolWebsiteMetadata(
        canonical_url=url,
        normalized_url=normalized_url,
        normalized_url_hash=_sha256(normalized_url),
        domain=domain,
        title=clean_title,
        description=clean_description,
        image_url=image_url[:1024],
        raw_metadata=metadata,
        source_fingerprint=_sha256(fingerprint_payload),
    )


def _fallback_metadata(url: str, *, status_code: int | None = None, reason: str = "") -> ToolWebsiteMetadata:
    parsed = urlparse(url)
    domain = (parsed.hostname or "").lower().rstrip(".")
    return _make_metadata(
        url,
        title=_friendly_domain_title(domain),
        description=reason or "目标网站拒绝自动抓取，已根据 URL 创建待 AI 富化的基础条目。",
        image_url=_default_favicon_url(url),
        raw_metadata={
            "fallback": True,
            "status_code": status_code,
            "fetch_error": reason,
        },
    )


def build_manual_tool_website_metadata(
    raw_url: str,
    *,
    title: str,
    description: str,
) -> ToolWebsiteMetadata:
    """Build safe metadata from admin-provided fields without fetching the page."""
    url = _validate_url(raw_url)
    parsed = urlparse(url)
    domain = (parsed.hostname or "").lower().rstrip(".")
    return _make_metadata(
        url,
        title=title or domain,
        description=description,
        image_url=_default_favicon_url(url),
        raw_metadata={"manual": True, "logo_url": _default_favicon_url(url)},
    )

def _normalize_encoding(value: str) -> str:
    encoding = (value or "").strip().lower().replace(" ", "")
    return _ENCODING_ALIASES.get(encoding, encoding)


def _extract_charset(content_type: str, content: bytes) -> str:
    candidates: list[str] = []
    if content_type:
        match = _CHARSET_RE.search(content_type.encode("latin1", errors="ignore"))
        if match:
            candidates.append(match.group(1).decode("ascii", errors="ignore"))
    head = content[:4096]
    match = _META_CHARSET_RE.search(head)
    if match:
        candidates.append(match.group(1).decode("ascii", errors="ignore"))
    http_equiv = re.search(
        rb"<meta[^>]+http-equiv=[\"']?content-type[\"']?[^>]+content=[\"'][^\"']*charset=([^\"'\s;>]+)",
        head,
        re.IGNORECASE,
    )
    if http_equiv:
        candidates.append(http_equiv.group(1).decode("ascii", errors="ignore"))
    for candidate in candidates:
        normalized = _normalize_encoding(candidate)
        if normalized:
            return normalized
    return ""


def _mojibake_score(text: str) -> int:
    if not text:
        return 10_000
    bad_markers = ("�", "Ã", "Â", "Ð", "С", "�")
    score = sum(text.count(marker) * 20 for marker in bad_markers)
    score += text.count("?")
    # Penalize latin/cyrillic mojibake mixed with many replacement-ish fragments.
    score += len(re.findall(r"[Ѐ-ӿ][�?]", text)) * 10
    return score


def _decode_html(content: bytes, content_type: str = "") -> tuple[str, str]:
    preferred = _extract_charset(content_type, content)
    candidates: list[str] = []
    for encoding in (preferred, "utf-8", "gb18030", "big5", "shift_jis", "latin1"):
        normalized = _normalize_encoding(encoding)
        if normalized and normalized not in candidates:
            candidates.append(normalized)

    best_text = ""
    best_encoding = candidates[0] if candidates else "utf-8"
    best_score = 10_000_000
    for encoding in candidates:
        try:
            text = content.decode(encoding, errors="replace")
        except LookupError:
            continue
        score = _mojibake_score(text)
        if score < best_score:
            best_text = text
            best_encoding = encoding
            best_score = score
        if score == 0 and encoding == preferred:
            break
    return best_text, best_encoding


def _meta_content(soup: BeautifulSoup, *, property_name: str = "", name: str = "") -> str:
    if property_name:
        tag = soup.find("meta", attrs={"property": property_name})
        if tag and tag.get("content"):
            return clean_text(tag.get("content"), max_len=512)
    if name:
        tag = soup.find("meta", attrs={"name": name})
        if tag and tag.get("content"):
            return clean_text(tag.get("content"), max_len=512)
    return ""


def _absolute_url(base_url: str, value: str) -> str:
    if not value:
        return ""
    joined = urljoin(base_url, value)
    parsed = urlparse(joined)
    if parsed.scheme.lower() not in _ALLOWED_SCHEMES:
        return ""
    return joined


def _link_href_by_rel(soup: BeautifulSoup, rel_names: set[str]) -> str:
    for tag in soup.find_all("link"):
        raw_rel = tag.get("rel") or []
        if isinstance(raw_rel, str):
            rel_values = raw_rel.lower().split()
        else:
            rel_values = [str(item).lower() for item in raw_rel]
        if not rel_names.intersection(rel_values):
            continue
        href = str(tag.get("href") or "").strip()
        if href:
            return href
    return ""


def _first_text(soup: BeautifulSoup, selector: str, *, max_len: int = 512) -> str:
    tag = soup.select_one(selector)
    if not tag:
        return ""
    return clean_text(tag.get_text(" ", strip=True), max_len=max_len)


def _choose_best_text(candidates: list[str], fallback: str = "") -> str:
    best = ""
    best_score = 10_000_000
    for candidate in candidates:
        text = clean_text(candidate, max_len=512)
        if not text:
            continue
        score = _mojibake_score(text)
        if score < best_score:
            best = text
            best_score = score
    return best or fallback


def _looks_like_challenge_page(soup: BeautifulSoup, html: str) -> bool:
    lowered = html[:20_000].lower()
    challenge_markers = (
        "aliyun_waf",
        "waf-nc",
        "window._waf",
        "just a moment",
        "cf-chl",
        "cloudflare",
        "captcha",
        "人机验证",
        "安全验证",
    )
    if any(marker in lowered for marker in challenge_markers):
        return True
    title = clean_text(soup.title.string if soup.title and soup.title.string else "", max_len=120).lower()
    return title in {"just a moment...", "403 forbidden", ""} and any(
        marker in lowered for marker in ("waf", "captcha", "challenge", "verify")
    )


def _extract_metadata(final_url: str, html: str, *, encoding: str = "") -> ToolWebsiteMetadata:
    soup = BeautifulSoup(html, "html.parser")
    parsed = urlparse(final_url)
    domain = (parsed.hostname or "").lower().rstrip(".")

    if _looks_like_challenge_page(soup, html):
        return _fallback_metadata(
            final_url,
            status_code=200,
            reason="目标网站返回 WAF/人机验证页，未能读取真实标题和描述，已用域名创建基础条目。",
        )

    og_title = _meta_content(soup, property_name="og:title")
    twitter_title = _meta_content(soup, name="twitter:title")
    html_title = clean_text(soup.title.string if soup.title and soup.title.string else "", max_len=512)
    app_name = _meta_content(soup, name="application-name")
    site_name = _meta_content(soup, property_name="og:site_name")
    h1_title = _first_text(soup, "h1")
    title = _choose_best_text(
        [og_title, twitter_title, html_title, app_name, site_name, h1_title],
        fallback=domain,
    )

    og_description = _meta_content(soup, property_name="og:description")
    twitter_description = _meta_content(soup, name="twitter:description")
    meta_description = _meta_content(soup, name="description")
    first_paragraph = _first_text(soup, "main p, article p, body p", max_len=1024)
    description = _choose_best_text(
        [og_description, twitter_description, meta_description, first_paragraph],
        fallback="",
    )

    logo_url = ""
    image_url = ""
    for logo_candidate in (
        _absolute_url(final_url, _link_href_by_rel(soup, {"apple-touch-icon", "apple-touch-icon-precomposed"})),
        _absolute_url(final_url, _link_href_by_rel(soup, {"icon", "shortcut"})),
        _absolute_url(final_url, _link_href_by_rel(soup, {"mask-icon"})),
        _default_favicon_url(final_url),
    ):
        if not logo_candidate:
            continue
        try:
            logo_url = _validate_url(logo_candidate)
            break
        except ToolWebsiteFetchError:
            continue
    for image_candidate in (
        logo_url,
        _absolute_url(final_url, _meta_content(soup, property_name="og:image")),
        _absolute_url(final_url, _meta_content(soup, name="twitter:image")),
    ):
        if not image_candidate:
            continue
        try:
            image_url = _validate_url(image_candidate)
            break
        except ToolWebsiteFetchError:
            continue

    canonical_url = final_url
    canonical_link = soup.find("link", attrs={"rel": lambda rel: rel and "canonical" in rel})
    if canonical_link and canonical_link.get("href"):
        candidate = _absolute_url(final_url, str(canonical_link.get("href")))
        try:
            safe_candidate = _validate_url(candidate)
            if urlparse(safe_candidate).hostname == domain:
                canonical_url = safe_candidate
        except ToolWebsiteFetchError:
            pass

    normalized_url = _normalize_url(canonical_url)
    raw_metadata = {
        "encoding": encoding,
        "og_title": og_title,
        "twitter_title": twitter_title,
        "html_title": html_title,
        "application_name": app_name,
        "site_name": site_name,
        "h1_title": h1_title,
        "og_description": og_description,
        "twitter_description": twitter_description,
        "meta_description": meta_description,
        "first_paragraph": first_paragraph,
        "logo_url": logo_url,
        "image_url": image_url,
    }
    fingerprint_payload = json.dumps(
        {
            "url": normalized_url,
            "domain": domain,
            "title": title,
            "description": description,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return ToolWebsiteMetadata(
        canonical_url=canonical_url,
        normalized_url=normalized_url,
        normalized_url_hash=_sha256(normalized_url),
        domain=domain,
        title=clean_text(title, max_len=512),
        description=clean_text(description, max_len=1024),
        image_url=image_url[:1024],
        raw_metadata=raw_metadata,
        source_fingerprint=_sha256(fingerprint_payload),
    )


def _read_limited_response(response: httpx.Response) -> bytes:
    chunks: list[bytes] = []
    total = 0
    for chunk in response.iter_bytes(chunk_size=65_536):
        if not chunk:
            continue
        total += len(chunk)
        if total > _MAX_BYTES:
            raise ToolWebsiteFetchError("网页内容过大")
        chunks.append(chunk)
    return b"".join(chunks)


def _validated_proxy_url(raw_proxy_url: str) -> str | None:
    proxy_url = (raw_proxy_url or "").strip()
    if not proxy_url:
        return None
    try:
        parsed = urlparse(proxy_url)
        port = parsed.port
    except ValueError as exc:
        raise ToolWebsiteFetchError("出站代理配置无效") from exc
    if parsed.scheme.lower() not in {"http", "https", "socks5", "socks5h"}:
        raise ToolWebsiteFetchError("出站代理配置无效")
    if not parsed.hostname or port is None or not 1 <= port <= 65_535:
        raise ToolWebsiteFetchError("出站代理配置无效")
    if parsed.path not in {"", "/"} or parsed.params or parsed.query or parsed.fragment:
        raise ToolWebsiteFetchError("出站代理配置无效")
    return proxy_url


def _proxy_uses_remote_dns(proxy_url: str, hostname: str) -> bool:
    proxy_scheme = urlparse(proxy_url).scheme.lower()
    host = hostname.lower().rstrip(".")
    return proxy_scheme == "socks5h" and any(
        host == allowed_host or host.endswith(f".{allowed_host}")
        for allowed_host in _REMOTE_DNS_PROXY_HOSTS
    )


def _proxy_request_target(logical_url: str) -> tuple[str, dict[str, str], dict[str, Any]]:
    try:
        target = pin_http_target(
            logical_url,
            allowed_ports={80, 443},
            resolver=lambda hostname: _safe_resolved_ips(hostname),
        )
    except OutboundTargetPolicyError as exc:
        raise ToolWebsiteFetchError(str(exc)) from exc
    return target.request_url, target.headers, target.extensions


def _fetch_tool_website_metadata(
    raw_url: str,
    *,
    proxy_url: str | None = None,
) -> ToolWebsiteMetadata:
    current_url = _validate_url(raw_url)
    headers = {
        "User-Agent": _USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    timeout = httpx.Timeout(timeout=12.0, connect=5.0, read=10.0)

    with httpx.Client(
        timeout=timeout,
        follow_redirects=False,
        trust_env=False,
        headers=headers,
        proxy=proxy_url,
    ) as client:
        for _ in range(_MAX_REDIRECTS + 1):
            hostname = urlparse(current_url).hostname or ""
            if proxy_url and _proxy_uses_remote_dns(proxy_url, hostname):
                # Some blocked domains receive poisoned local DNS answers. This narrow allowlist
                # deliberately relies on the trusted SOCKS resolver; redirects are revalidated.
                request_url = current_url
                request_headers = {}
                extensions = {}
                request_context = nullcontext()
            elif proxy_url:
                request_url, request_headers, extensions = _proxy_request_target(current_url)
                request_context = nullcontext()
            else:
                request_url, request_headers, extensions = _proxy_request_target(current_url)
                request_context = nullcontext()

            with request_context:
                with client.stream(
                    "GET",
                    request_url,
                    headers=request_headers,
                    extensions=extensions,
                ) as response:
                    if response.status_code in (301, 302, 303, 307, 308):
                        location = response.headers.get("location")
                        if not location:
                            raise ToolWebsiteFetchError("重定向缺少 Location")
                        current_url = _validate_url(urljoin(current_url, location))
                        continue

                    if response.status_code in _BLOCKED_STATUS_CODES:
                        return _fallback_metadata(
                            current_url,
                            status_code=response.status_code,
                            reason=f"目标网站返回 {response.status_code}，可能启用了登录、WAF 或反爬限制，已用 URL 创建基础条目。",
                        )
                    try:
                        response.raise_for_status()
                    except httpx.HTTPStatusError as exc:
                        raise ToolWebsiteFetchError(f"目标网站返回 HTTP {response.status_code}") from exc

                    content_type = response.headers.get("content-type", "").lower()
                    if content_type and "html" not in content_type and "xhtml" not in content_type:
                        raise ToolWebsiteFetchError("目标 URL 不是 HTML 页面")
                    content_length = response.headers.get("content-length")
                    if content_length:
                        try:
                            content_length_value = int(content_length)
                        except ValueError:
                            content_length_value = 0
                        if content_length_value > _MAX_BYTES:
                            raise ToolWebsiteFetchError("网页内容过大")

                    content = _read_limited_response(response)
                    html, encoding = _decode_html(content, content_type)
                    return _extract_metadata(current_url, html, encoding=encoding)

    raise ToolWebsiteFetchError("重定向次数过多")


def fetch_tool_website_metadata(raw_url: str) -> ToolWebsiteMetadata:
    try:
        return _fetch_tool_website_metadata(raw_url)
    except httpx.RequestError as direct_exc:
        try:
            proxy_url = _validated_proxy_url(settings.outbound_proxy)
            if not proxy_url:
                raise ToolWebsiteFetchError(f"无法连接目标网站：{direct_exc}") from direct_exc
            return _fetch_tool_website_metadata(raw_url, proxy_url=proxy_url)
        except httpx.RequestError as proxy_exc:
            raise ToolWebsiteFetchError("直接连接和出站代理均无法访问目标网站") from proxy_exc
