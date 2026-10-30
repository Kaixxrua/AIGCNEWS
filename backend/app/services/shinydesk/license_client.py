"""闪光工坊授权服务器的发码客户端（服务器之间，HMAC-SHA256 鉴权）。

签名串（与授权服务器 purchases.cjs 一致，换行分隔）：
    SHINY-PURCHASE-V1 / POST / 路径 / 毫秒时间戳 / nonce / sha256(body) hex
路径是授权服务器看到的路径（Caddy handle_path 已去掉 /shiny-service 前缀），
即 /v1/internal/purchases/{issue,revoke,status}。服务端 ±5 分钟窗口 + nonce
防重放；幂等键 = PayPal 订单号，重复 issue 返回同一个码。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import httpx

from backend.app.services.shinydesk.product import (
    AMOUNT_CENTS,
    CURRENCY,
    LICENSE_PRODUCT,
    ShinyDeskConfig,
)

_CONTEXT = "SHINY-PURCHASE-V1"
_TIMEOUT_SECONDS = 10.0
_PATH_PREFIX = "/v1/internal/purchases/"
REVOKE_REASONS = frozenset({"refund", "reversal", "dispute", "manual"})


class LicenseServiceError(RuntimeError):
    """授权服务器不可达或 5xx：调用方保持订单 paid 状态，后续回调/查询重试。"""


class LicenseServiceRejected(LicenseServiceError):
    """授权服务器 4xx（鉴权/参数/冲突）：需要人工排查，不自动重试同一请求体。"""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(f"license service rejected: HTTP {status_code} {message}")
        self.status_code = status_code


@dataclass(frozen=True)
class IssuedLicense:
    code: str
    license_id: str
    revoked: bool
    replayed: bool


def signature(secret: bytes, *, path: str, timestamp: str, nonce: str, body: bytes) -> str:
    message = "\n".join(
        [_CONTEXT, "POST", path, timestamp, nonce, hashlib.sha256(body).hexdigest()]
    )
    return hmac.new(secret, message.encode("utf-8"), hashlib.sha256).hexdigest()


def read_key_file(path: str) -> bytes:
    secret = Path(path).read_text(encoding="utf-8").strip().encode("utf-8")
    if len(secret) < 32:
        raise LicenseServiceError("license HMAC key file must hold at least 32 bytes")
    return secret


class ShinyDeskLicenseClient:
    def __init__(
        self,
        *,
        base_url: str,
        key_id: str,
        secret: bytes,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._key_id = key_id
        self._secret = secret
        self._transport = transport
        self._clock = clock

    def _call(self, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        path = _PATH_PREFIX + action
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        timestamp = str(int(self._clock() * 1000))
        nonce = secrets.token_urlsafe(24)
        headers = {
            "Content-Type": "application/json",
            "X-Purchase-Key": self._key_id,
            "X-Purchase-Timestamp": timestamp,
            "X-Purchase-Nonce": nonce,
            "X-Purchase-Signature": signature(
                self._secret, path=path, timestamp=timestamp, nonce=nonce, body=body
            ),
        }
        try:
            # 服务器之间直连：生产出站代理（OUTBOUND_PROXY）对 aigcnews.cn 的 TLS 会被中断。
            with httpx.Client(
                transport=self._transport, timeout=_TIMEOUT_SECONDS, trust_env=False
            ) as client:
                response = client.post(self._base_url + path, content=body, headers=headers)
        except httpx.HTTPError as exc:
            raise LicenseServiceError(f"license service unreachable: {exc}") from exc
        try:
            data = response.json()
        except ValueError:
            data = {}
        if not isinstance(data, dict):
            data = {}
        if 400 <= response.status_code < 500:
            raise LicenseServiceRejected(response.status_code, str(data.get("error") or ""))
        if response.status_code != 200 or data.get("ok") is not True or not isinstance(data.get("result"), dict):
            raise LicenseServiceError(f"license service failed: HTTP {response.status_code}")
        return data["result"]

    def issue(self, *, paypal_order_id: str, order_no: str) -> IssuedLicense:
        result = self._call(
            "issue",
            {
                "orderId": paypal_order_id,
                "orderNo": order_no,
                "product": LICENSE_PRODUCT,
                "amountCents": AMOUNT_CENTS,
                "currency": CURRENCY,
            },
        )
        code = result.get("code")
        license_id = result.get("licenseId")
        if not isinstance(code, str) or not code.startswith("PB-") or not isinstance(license_id, str):
            raise LicenseServiceError("license service returned no code")
        if result.get("orderId") != paypal_order_id or result.get("orderNo") != order_no:
            raise LicenseServiceError("license service returned another order")
        return IssuedLicense(
            code=code,
            license_id=license_id,
            revoked=bool(result.get("revoked")),
            replayed=bool(result.get("replayed")),
        )

    def revoke(self, *, paypal_order_id: str, reason: str) -> dict[str, Any]:
        if reason not in REVOKE_REASONS:
            raise ValueError(f"invalid revoke reason: {reason!r}")
        return self._call("revoke", {"orderId": paypal_order_id, "reason": reason})

    def status(self, *, paypal_order_id: str) -> dict[str, Any]:
        return self._call("status", {"orderId": paypal_order_id})


def build_license_client(config: ShinyDeskConfig) -> ShinyDeskLicenseClient | None:
    """配置不全返回 None（下单前 503）；密钥文件读不到同样视为未配置。"""
    if not config.license_configured:
        return None
    try:
        secret = read_key_file(config.license_key_file)
    except (OSError, LicenseServiceError):
        return None
    return ShinyDeskLicenseClient(
        base_url=config.license_api_base, key_id=config.license_key_id, secret=secret
    )
