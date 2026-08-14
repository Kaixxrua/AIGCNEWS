"""邮件投递目标的 SSRF 守卫（面板/管理 API 写入路径共用）。

自 smtp_config_admin 抽取，供 SMTP 单配置与邮件池配置两处校验复用；
行为与抽取前完全一致。仅约束面板写入路径，env 配置路径不受影响。
"""

from __future__ import annotations

import ipaddress
import re

# 主机字段只允许纯主机名或 IPv4 字面量：":///@" 可注入协议、端口或凭证
_HOST_FORBIDDEN_CHARS = re.compile(r"[\s/@:]")
_DENIED_HOSTNAMES = {"localhost", "metadata.google.internal"}

FROM_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def validate_email_host(host: str) -> str:
    """归一化并拦截危险投递目标（渗透审计 SSRF-3），返回规范化主机名。

    允许私网段（RFC1918）：内网邮件中继是合法部署形态；拦截回环、链路
    本地、组播、未指定与保留地址及 localhost 系主机名，防本机服务探测
    与凭证外送。不做保存期 DNS：docker 内部主机名仅在发送时网络视图可
    解析，保存期解析会误杀合法配置。IPv6 字面量因与端口分隔符冲突不在
    面板路径支持（env 路径不受影响）。
    """
    normalized = host.strip().lower().rstrip(".")
    if not normalized or len(normalized) > 253 or _HOST_FORBIDDEN_CHARS.search(normalized):
        raise ValueError("SMTP 主机名不合法：仅允许主机名或 IPv4 地址，不含协议/端口/凭证")
    if normalized in _DENIED_HOSTNAMES or normalized.endswith(".localhost"):
        raise ValueError("SMTP 主机不允许指向本机或保留地址")
    try:
        ip = ipaddress.ip_address(normalized)
    except ValueError:
        return normalized
    if (
        ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_unspecified
        or ip.is_reserved
    ):
        raise ValueError("SMTP 主机不允许指向本机或保留地址")
    return normalized
