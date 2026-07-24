from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from typing import Callable, Iterable
from urllib.parse import urldefrag, urlparse, urlunparse

_DENIED_HOSTS = {"localhost", "metadata.google.internal"}
_ALLOWED_SCHEMES = {"http", "https"}


class OutboundTargetPolicyError(ValueError):
    """Raised when an outbound HTTP target is not safe to contact."""


Resolver = Callable[[str], Iterable[str]]


@dataclass(frozen=True)
class PinnedHttpTarget:
    logical_url: str
    request_url: str
    host_header: str
    sni_hostname: str
    selected_ip: str

    @property
    def headers(self) -> dict[str, str]:
        return {"Host": self.host_header}

    @property
    def extensions(self) -> dict[str, str]:
        return {"sni_hostname": self.sni_hostname}


def is_safe_public_ip(value: str | ipaddress._BaseAddress) -> bool:
    try:
        ip = value if isinstance(value, ipaddress._BaseAddress) else ipaddress.ip_address(value)
    except ValueError:
        return False
    return bool(
        ip.is_global
        and not ip.is_private
        and not ip.is_loopback
        and not ip.is_link_local
        and not ip.is_multicast
        and not ip.is_unspecified
        and not ip.is_reserved
    )


def _system_resolver(hostname: str) -> list[str]:
    try:
        infos = socket.getaddrinfo(hostname, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise OutboundTargetPolicyError(f"无法解析域名：{hostname}") from exc
    return [str(info[4][0]) for info in infos]


def resolve_public_ips(
    hostname: str,
    *,
    resolver: Resolver | None = None,
    reject_mixed: bool = False,
) -> tuple[str, ...]:
    host = (hostname or "").strip().lower().rstrip(".")
    if not host or host in _DENIED_HOSTS or host.endswith(".localhost"):
        raise OutboundTargetPolicyError("不允许访问本地、内网或保留地址")

    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        answers = list((resolver or _system_resolver)(host))
    else:
        answers = [str(literal)]

    safe: list[str] = []
    unsafe_found = False
    seen: set[str] = set()
    for answer in answers:
        try:
            normalized = str(ipaddress.ip_address(answer))
        except ValueError:
            unsafe_found = True
            continue
        if not is_safe_public_ip(normalized):
            unsafe_found = True
            continue
        if normalized not in seen:
            seen.add(normalized)
            safe.append(normalized)

    if not safe or (reject_mixed and unsafe_found):
        raise OutboundTargetPolicyError("不允许访问本地、内网或保留地址")
    return tuple(safe)


def normalize_http_url(
    raw_url: str,
    *,
    allowed_ports: set[int] | None = None,
    add_default_scheme: bool = False,
    max_length: int = 1024,
) -> str:
    url = (raw_url or "").strip()
    if not url:
        raise OutboundTargetPolicyError("URL 不能为空")
    if len(url) > max_length:
        raise OutboundTargetPolicyError("URL 过长")
    if add_default_scheme and "://" not in url:
        url = f"https://{url}"
    url, _fragment = urldefrag(url)
    parsed = urlparse(url)
    if parsed.scheme.lower() not in _ALLOWED_SCHEMES:
        raise OutboundTargetPolicyError("只支持 http/https URL")
    if parsed.username or parsed.password:
        raise OutboundTargetPolicyError("URL 不能包含用户名或密码")
    hostname = (parsed.hostname or "").strip().lower().rstrip(".")
    if not hostname:
        raise OutboundTargetPolicyError("URL 缺少域名")
    try:
        port = parsed.port
    except ValueError as exc:
        raise OutboundTargetPolicyError("URL 端口无效") from exc
    if allowed_ports is not None and port is not None and port not in allowed_ports:
        raise OutboundTargetPolicyError("URL 端口不在允许范围内")

    host_for_url = f"[{hostname}]" if ":" in hostname else hostname
    netloc = f"{host_for_url}:{port}" if port is not None else host_for_url
    return urlunparse((parsed.scheme.lower(), netloc, parsed.path or "/", "", parsed.query, ""))


def pin_http_target(
    raw_url: str,
    *,
    resolver: Resolver | None = None,
    reject_mixed: bool = False,
    allowed_ports: set[int] | None = None,
    add_default_scheme: bool = False,
) -> PinnedHttpTarget:
    logical_url = normalize_http_url(
        raw_url,
        allowed_ports=allowed_ports,
        add_default_scheme=add_default_scheme,
    )
    parsed = urlparse(logical_url)
    hostname = parsed.hostname or ""
    safe_ips = resolve_public_ips(hostname, resolver=resolver, reject_mixed=reject_mixed)
    selected_ip = next((ip for ip in safe_ips if ":" not in ip), safe_ips[0])
    ip_host = f"[{selected_ip}]" if ":" in selected_ip else selected_ip
    netloc = f"{ip_host}:{parsed.port}" if parsed.port is not None else ip_host
    request_url = urlunparse((parsed.scheme, netloc, parsed.path, "", parsed.query, ""))

    default_port = 80 if parsed.scheme == "http" else 443
    host_header = hostname if parsed.port in {None, default_port} else f"{hostname}:{parsed.port}"
    return PinnedHttpTarget(
        logical_url=logical_url,
        request_url=request_url,
        host_header=host_header,
        sni_hostname=hostname,
        selected_ip=selected_ip,
    )
