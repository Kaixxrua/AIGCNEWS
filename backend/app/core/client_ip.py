"""可信代理感知的客户端 IP 解析。

X-Forwarded-For 是可伪造的请求头：仅当直连对端（``request.client.host``）
命中 ``settings.trusted_proxy_ips``（可信反向代理列表，支持 IP/CIDR）时
才采信其首跳，否则一律以直连对端为准。限速、访客统计等按 IP 归因的逻辑
统一走这里，避免各路由各自解析 XFF 的信任口径漂移。

部署口径：生产前端 nginx 覆写 XFF 后经编排内网回源（docker-compose），
把编排网段配入 TRUSTED_PROXY_IPS 即可恢复真实客户端归因；默认仅回环，
单机直跑与本机调试开箱即安全。
"""

from __future__ import annotations

import ipaddress
import logging
from functools import lru_cache

from starlette.requests import Request

from backend.app.core.config import settings

logger = logging.getLogger(__name__)

IpNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network


def _parse_trusted_proxy_networks(raw: str) -> tuple[IpNetwork, ...]:
    networks: list[IpNetwork] = []
    for item in (raw or "").split(","):
        entry = item.strip()
        if not entry:
            continue
        try:
            networks.append(ipaddress.ip_network(entry, strict=False))
        except ValueError:
            logger.warning("[ClientIP] 忽略非法的可信代理配置项: %r", entry)
    return tuple(networks)


@lru_cache(maxsize=1)
def _trusted_proxy_networks() -> tuple[IpNetwork, ...]:
    return _parse_trusted_proxy_networks(settings.trusted_proxy_ips)


def _reset_trusted_proxy_cache() -> None:
    """测试缝：monkeypatch settings.trusted_proxy_ips 后调用。"""
    _trusted_proxy_networks.cache_clear()


def is_trusted_proxy(host: str) -> bool:
    """直连对端是否为可信反向代理（不可解析的地址一律不可信）。"""
    try:
        address = ipaddress.ip_address((host or "").strip())
    except ValueError:
        return False
    return any(address in network for network in _trusted_proxy_networks())


def client_ip_from_request(request: Request) -> str:
    """解析客户端 IP：可信代理转发时取 XFF 首跳，否则取直连对端。"""
    peer = request.client.host if request.client else ""
    if peer and is_trusted_proxy(peer):
        forwarded_for = request.headers.get("x-forwarded-for")
        if forwarded_for:
            first_hop = forwarded_for.split(",")[0].strip()
            if first_hop:
                return first_hop
    return peer or "unknown"
