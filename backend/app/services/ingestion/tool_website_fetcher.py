from __future__ import annotations

"""Safe metadata fetching for admin-added AI tool websites."""

import hashlib
import ipaddress
import json
import re
import socket
from contextlib import contextmanager
from dataclasses import dataclass
from threading import RLock
from typing import Any, Dict, Iterator
from urllib.parse import urldefrag, urljoin, urlparse, urlunparse

import httpx
from bs4 import BeautifulSoup

from backend.app.services.ingestion.project_taxonomy import clean_text

_MAX_REDIRECTS = 3
_MAX_BYTES = 1_000_000
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36 AIGC-NEWS-ToolWebsiteBot/1.0"
)
_ALLOWED_SCHEMES = {"http", "https"}
_DENIED_HOSTS = {"localhost", "metadata.google.internal"}
_BLOCKED_STATUS_CODES = {401, 403, 429, 503}
_CHARSET_RE = re.compile(rb"charset=[\"']?([a-zA-Z0-9_\-]+)", re.IGNORECASE)
_META_CHARSET_RE = re.compile(rb"<meta[^>]+charset=[\"']?\s*([a-zA-Z0-9_\-]+)", re.IGNORECASE)
_ENCODING_ALIASES = {
    "gb2312": "gb18030",
    "gbk": "gb18030",
    "gb_2312-80": "gb18030",
    "x-gbk": "gb18030",
}
_DNS_PIN_LOCK = RLock()


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


def _ip_is_local_or_dangerous(ip: ipaddress._BaseAddress) -> bool:
    return bool(
        ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_unspecified
        or (ip.version == 4 and ip.is_private)
        or (ip.version == 6 and str(ip).lower().startswith("fc"))
        or (ip.version == 6 and str(ip).lower().startswith("fd"))
    )


def _ip_is_safe_public(ip: ipaddress._BaseAddress) -> bool:
    return not (_ip_is_local_or_dangerous(ip) or ip.is_reserved or not ip.is_global)


def _safe_resolved_ips(hostname: str) -> list[str]:
    host = (hostname or "").strip().lower().rstrip(".")
    if not host:
        return []
    if host in _DENIED_HOSTS or host.endswith(".localhost"):
        return []

    try:
        ip = ipaddress.ip_address(host)
        if not _ip_is_safe_public(ip):
            return []
        return [str(ip)]
    except ValueError:
        pass

    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise ToolWebsiteFetchError(f"无法解析域名：{host}") from exc

    safe_ips: list[str] = []
    seen: set[str] = set()
    for info in infos:
        address = info[4][0]
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            continue
        # Some DNS resolvers return unusable placeholder IPv6 records alongside valid public A
        # records. Pin requests only to the public addresses instead of rejecting the domain.
        if not _ip_is_safe_public(ip):
            continue
        ip_text = str(ip)
        if ip_text not in seen:
            seen.add(ip_text)
            safe_ips.append(ip_text)
    return safe_ips


def _host_is_safe(hostname: str) -> bool:
    return bool(_safe_resolved_ips(hostname))


def _validate_url(raw_url: str) -> str:
    url = (raw_url or "").strip()
    if not url:
        raise ToolWebsiteFetchError("URL 不能为空")
    if len(url) > 1024:
        raise ToolWebsiteFetchError("URL 过长")
    if "://" not in url:
        url = f"https://{url}"

    url, _fragment = urldefrag(url)
    parsed = urlparse(url)
    if parsed.scheme.lower() not in _ALLOWED_SCHEMES:
        raise ToolWebsiteFetchError("只支持 http/https URL")
    if parsed.username or parsed.password:
        raise ToolWebsiteFetchError("URL 不能包含用户名或密码")
    if parsed.port and parsed.port not in (80, 443):
        raise ToolWebsiteFetchError("只允许标准 HTTP/HTTPS 端口")
    hostname = (parsed.hostname or "").strip().lower().rstrip(".")
    if not _host_is_safe(hostname):
        raise ToolWebsiteFetchError("不允许访问本地、内网或保留地址")

    netloc = hostname
    if parsed.port:
        netloc = f"{hostname}:{parsed.port}"
    path = parsed.path or "/"
    return urlunparse((parsed.scheme.lower(), netloc, path, "", parsed.query, ""))


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


@contextmanager
def _pin_safe_dns_resolution(hostname: str) -> Iterator[None]:
    """Keep httpx on the same pre-validated public addresses during one fetch."""
    host = (hostname or "").strip().lower().rstrip(".")
    if not host:
        raise ToolWebsiteFetchError("URL 缺少域名")
    with _DNS_PIN_LOCK:
        safe_ips = _safe_resolved_ips(host)
        if not safe_ips:
            raise ToolWebsiteFetchError("不允许访问本地、内网或保留地址")

        original_getaddrinfo = socket.getaddrinfo

        def pinned_getaddrinfo(request_host: str, port: Any, *args: Any, **kwargs: Any):
            normalized_request_host = (request_host or "").strip().lower().rstrip(".")
            if normalized_request_host != host:
                return original_getaddrinfo(request_host, port, *args, **kwargs)
            results = []
            for ip_text in safe_ips:
                family = socket.AF_INET6 if ":" in ip_text else socket.AF_INET
                sockaddr = (ip_text, port, 0, 0) if family == socket.AF_INET6 else (ip_text, port)
                results.append((family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", sockaddr))
            return results

        socket.getaddrinfo = pinned_getaddrinfo
        try:
            yield
        finally:
            socket.getaddrinfo = original_getaddrinfo


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


def _fetch_tool_website_metadata(raw_url: str, *, trust_env: bool = False) -> ToolWebsiteMetadata:
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
        trust_env=trust_env,
        headers=headers,
    ) as client:
        for _ in range(_MAX_REDIRECTS + 1):
            hostname = urlparse(current_url).hostname or ""
            with _pin_safe_dns_resolution(hostname):
                with client.stream("GET", current_url) as response:
                    if response.status_code in (301, 302, 303, 307, 308):
                        location = response.headers.get("location")
                        if not location:
                            raise ToolWebsiteFetchError("重定向缺少 Location")
                        current_url = _validate_url(urljoin(current_url, location))
                        continue

                    if response.status_code in _BLOCKED_STATUS_CODES:
                        return _fallback_metadata(
                            str(response.url),
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
                    return _extract_metadata(str(response.url), html, encoding=encoding)

    raise ToolWebsiteFetchError("重定向次数过多")


def fetch_tool_website_metadata(raw_url: str) -> ToolWebsiteMetadata:
    try:
        # This SSRF-sensitive fetcher must keep local DNS validation and pinning.
        # Remote DNS through socks5h would invalidate that security boundary.
        return _fetch_tool_website_metadata(raw_url, trust_env=False)
    except httpx.RequestError as direct_exc:
        raise ToolWebsiteFetchError(f"无法连接目标网站：{direct_exc}") from direct_exc
