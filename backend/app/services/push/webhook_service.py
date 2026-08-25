"""Webhook 推送渠道：URL 平台识别、SSRF 防护、平台化载荷与分块投递。

渠道模型：target 存完整 URL（唯一约束与用户可见地址），encrypted_config
存密封后的 ``{"url": ...}`` 作为投递凭据；创建时先做一次真实探测投递，
成功才落库为 verified（webhook 无 OTP 通道，探测即验证）。

安全边界（Red）：
- 仅允许 https；拒绝携带 userinfo；
- 主机名按出站目标策略解析，任一解析结果不是公网地址
  （私网/回环/链路本地/保留/组播段）即拒绝，创建与每次投递前都校验；
- 投递时把校验过的 IP 固定进连接（Host/SNI 保持原主机），校验与连接
  共用同一次解析结果，消除 DNS 重绑定 TOCTOU 窗口；
- 请求不跟随重定向，超时收紧，平台侧 errcode 非 0 视为失败。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from urllib.parse import urlsplit

import httpx

from backend.app.services.outbound_target_policy import (
    OutboundTargetPolicyError,
    PinnedHttpTarget,
    pin_http_target,
    resolve_public_ips,
)
from backend.app.services.push.errors import WebhookDeliveryError, WebhookUrlError

logger = logging.getLogger(__name__)

PROVIDER_GENERIC = "generic"
PROVIDER_WECOM = "wecom"  # 企业微信群机器人
PROVIDER_DINGTALK = "dingtalk"  # 钉钉自定义机器人
PROVIDER_LARK = "lark"  # 飞书自定义机器人
PROVIDER_DISCORD = "discord"
PROVIDER_TELEGRAM = "telegram"

_PROVIDER_HOSTS = {
    "discord.com": PROVIDER_DISCORD,
    "discordapp.com": PROVIDER_DISCORD,
    "qyapi.weixin.qq.com": PROVIDER_WECOM,
    "oapi.dingtalk.com": PROVIDER_DINGTALK,
    "open.feishu.cn": PROVIDER_LARK,
    "open.larksuite.com": PROVIDER_LARK,
}

MAX_WEBHOOK_URL_LENGTH = 2048
MAX_CHUNKS = 6
DEFAULT_TIMEOUT_SECONDS = 5.0

# 各平台单条消息 UTF-8 字节预算（留头部余量，避免顶到硬上限）。
_CHUNK_BYTE_BUDGET = {
    PROVIDER_WECOM: 3500,  # 企业微信 markdown 上限 4096 字节
    PROVIDER_DINGTALK: 18000,  # 钉钉 markdown 上限约 20000 字节
    PROVIDER_LARK: 28000,
    PROVIDER_GENERIC: 28000,
    PROVIDER_DISCORD: 1900,
    PROVIDER_TELEGRAM: 3500,  # Telegram 单条上限 4096 字符
}

_OVERFLOW_FOOTER = "\n\n…内容过长已截断，完整报告见 https://aigcnews.cn"


def detect_provider(url: str) -> str:
    """按主机名识别机器人平台；未知主机按通用 JSON 投递。"""
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower()
    if host in {"discord.com", "discordapp.com"} and not parsed.path.startswith("/api/webhooks/"):
        return PROVIDER_GENERIC
    return _PROVIDER_HOSTS.get(host, PROVIDER_GENERIC)


def _host_is_public(host: str) -> bool:
    """主机字面量或其全部 DNS 解析结果均为公网地址（与出站目标策略同口径）。"""
    try:
        resolve_public_ips(host, reject_mixed=True)
    except OutboundTargetPolicyError:
        return False
    return True


def validate_webhook_url(raw: str) -> str:
    """规范化并校验 webhook URL（含 SSRF 防护）；不合法抛 WebhookUrlError。"""
    candidate = (raw or "").strip()
    if not candidate or len(candidate) > MAX_WEBHOOK_URL_LENGTH:
        raise WebhookUrlError("Webhook URL 非法")
    try:
        parsed = urlsplit(candidate)
    except ValueError as exc:
        raise WebhookUrlError("Webhook URL 非法") from exc
    if parsed.scheme != "https":
        raise WebhookUrlError("Webhook URL 必须使用 https")
    if parsed.username or parsed.password:
        raise WebhookUrlError("Webhook URL 不允许携带用户凭据")
    host = parsed.hostname
    if not host:
        raise WebhookUrlError("Webhook URL 缺少主机名")
    if not _host_is_public(host):
        raise WebhookUrlError("Webhook URL 主机不在允许范围（需为可解析的公网地址）")
    if host.lower() in {"discord.com", "discordapp.com"} and not parsed.path.startswith("/api/webhooks/"):
        raise WebhookUrlError("Discord Webhook URL 路径非法")
    return candidate


def _pin_webhook_target(url: str) -> PinnedHttpTarget:
    """把校验过的解析结果固定为连接目标，防 DNS 重绑定。

    请求 URL 使用本次解析出的公网 IP 字面量，Host 头与 TLS SNI 保持
    原主机名；连接阶段不再发生第二次独立 DNS 解析，校验时刻与连接
    时刻之间不存在解析漂移窗口。
    """
    try:
        return pin_http_target(url, reject_mixed=True)
    except OutboundTargetPolicyError as exc:
        raise WebhookUrlError(
            "Webhook URL 主机不在允许范围（需为可解析的公网地址）"
        ) from exc


def _validate_and_pin(raw: str) -> tuple[str, PinnedHttpTarget]:
    normalized = validate_webhook_url(raw)
    return normalized, _pin_webhook_target(normalized)


def build_webhook_payload(
    provider: str,
    *,
    title: str,
    content: str,
) -> dict[str, Any]:
    """按平台协议构造消息载荷；标题在各平台内的呈现方式不同。"""
    if provider == PROVIDER_WECOM:
        return {
            "msgtype": "markdown",
            "markdown": {"content": f"## {title}\n\n{content}"},
        }
    if provider == PROVIDER_DINGTALK:
        return {
            "msgtype": "markdown",
            "markdown": {"title": title, "text": f"## {title}\n\n{content}"},
        }
    if provider == PROVIDER_LARK:
        return {"msg_type": "text", "content": {"text": f"{title}\n\n{content}"}}
    if provider == PROVIDER_DISCORD:
        return {"content": f"**{title}**\n\n{content}"}
    return {"title": title, "text": content, "source": "aigcnews.cn"}


def _utf8_truncate(text: str, byte_budget: int) -> str:
    """按字节预算截断，保证不切断多字节字符。"""
    encoded = text.encode("utf-8")
    if len(encoded) <= byte_budget:
        return text
    return encoded[:byte_budget].decode("utf-8", errors="ignore")


def chunk_markdown_for_provider(provider: str, text: str) -> list[str]:
    """按平台字节预算在段落边界分块；超出块数上限时末块截断并加注脚。"""
    budget = _CHUNK_BYTE_BUDGET.get(provider, _CHUNK_BYTE_BUDGET[PROVIDER_GENERIC])
    chunks: list[str] = []
    current = ""
    for paragraph in text.split("\n\n"):
        candidate = paragraph if not current else f"{current}\n\n{paragraph}"
        if len(candidate.encode("utf-8")) <= budget:
            current = candidate
            continue
        if current:
            chunks.append(current)
            current = ""
        while len(paragraph.encode("utf-8")) > budget:
            cut = _utf8_truncate(paragraph, budget)
            chunks.append(cut)
            paragraph = paragraph[len(cut) :]
        current = paragraph
    if current:
        chunks.append(current)
    if not chunks:
        chunks = [""]
    if len(chunks) > MAX_CHUNKS:
        kept = chunks[:MAX_CHUNKS]
        footer_budget = budget - len(_OVERFLOW_FOOTER.encode("utf-8"))
        kept[-1] = _utf8_truncate(kept[-1], footer_budget) + _OVERFLOW_FOOTER
        return kept
    return chunks


class WebhookSender:
    """Webhook 投递器：每次发送前重新校验 URL，按平台分块顺序投递。"""

    def __init__(
        self,
        *,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._timeout_seconds = timeout_seconds
        self._transport = transport

    async def send(self, *, url: str, title: str, content: str) -> None:
        # 创建时校验过的 URL 在每次投递前重查并固定解析结果
        # （防 DNS 重绑定漂移：连接复用校验时刻的解析，不再独立解析）。
        normalized, target = await asyncio.to_thread(_validate_and_pin, url)
        provider = detect_provider(normalized)
        chunks = chunk_markdown_for_provider(provider, content)
        async with httpx.AsyncClient(
            timeout=self._timeout_seconds,
            transport=self._transport,
            follow_redirects=False,
            headers={"User-Agent": "AIGCNews-Webhook/1.0"},
        ) as client:
            for index, chunk in enumerate(chunks, start=1):
                payload = build_webhook_payload(provider, title=title, content=chunk)
                await self._post(client, target, provider, payload, index)

    async def _post(
        self,
        client: httpx.AsyncClient,
        target: PinnedHttpTarget,
        provider: str,
        payload: dict[str, Any],
        chunk_index: int,
    ) -> None:
        try:
            response = await client.post(
                target.request_url,
                json=payload,
                headers=target.headers,
                extensions=target.extensions,
            )
        except httpx.HTTPError as exc:
            raise WebhookDeliveryError(f"Webhook 请求失败：{exc}") from exc
        if response.status_code >= 400:
            raise WebhookDeliveryError(
                f"Webhook 返回 HTTP {response.status_code}（第 {chunk_index} 块）"
            )
        self._ensure_platform_success(provider, response, chunk_index)

    def _ensure_platform_success(
        self,
        provider: str,
        response: httpx.Response,
        chunk_index: int,
    ) -> None:
        """企业微信/钉钉/飞书 HTTP 200 也可能在响应体里报错。"""
        if provider in {PROVIDER_GENERIC, PROVIDER_DISCORD}:
            return
        try:
            data = response.json()
        except ValueError:
            return
        if not isinstance(data, dict):
            return
        code = data.get("errcode", data.get("code", data.get("StatusCode")))
        if isinstance(code, bool) or code is None:
            return
        try:
            numeric = int(code)
        except (TypeError, ValueError):
            return
        if numeric != 0:
            message = data.get("errmsg") or data.get("msg") or data.get("StatusMessage") or "unknown"
            raise WebhookDeliveryError(
                f"Webhook 平台拒绝（code={numeric}: {message}，第 {chunk_index} 块）"
            )
