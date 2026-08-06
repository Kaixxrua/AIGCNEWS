"""推送渠道凭据的静态加密边界。

复用微信会话的 AES-256-GCM secret box（信封含密钥版本号，支持轮换），
密钥来自 settings（URL-safe Base64 的 32 字节密钥 + 版本号）。email 渠道
没有凭据，不经过本模块；凡携带凭据的渠道类型在密钥缺失或非法时必须
拒绝处理 secret，绝不降级为明文存储。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from backend.app.core.config import settings
from backend.app.domain.wechat_secret_box import (
    WeChatSecretBox,
    WeChatSecretBoxError,
)

logger = logging.getLogger(__name__)


class PushChannelSecretError(Exception):
    """渠道凭据加解密失败或密钥配置不可用。"""


def build_push_channel_secret_box(*, config=settings) -> WeChatSecretBox | None:
    """构建渠道凭据加密盒；未配置或密钥非法时返回 None。

    返回 None 不阻塞应用启动（对齐微信密钥的装配策略）：无凭据的 email
    渠道不受影响，需要加密的渠道类型在使用处自行拒绝。
    """
    key = config.push_channel_encryption_key
    if not key:
        return None
    try:
        return WeChatSecretBox.from_urlsafe_base64(
            key,
            config.push_channel_encryption_key_version,
        )
    except WeChatSecretBoxError as exc:
        logger.warning("推送渠道加密密钥非法: %s", exc)
        return None


def seal_channel_config(
    box: WeChatSecretBox | None,
    config: dict[str, Any],
) -> str:
    """把渠道凭据 JSON 密封为可入库的信封字符串；无加密盒时拒绝。"""
    if box is None:
        raise PushChannelSecretError("推送渠道加密密钥未配置，无法存储渠道凭据")
    envelope = box.seal(json.dumps(config, ensure_ascii=False))
    return json.dumps(envelope, ensure_ascii=False)


def unseal_channel_config(
    box: WeChatSecretBox | None,
    encrypted_config: str,
) -> dict[str, Any]:
    """解封 :func:`seal_channel_config` 产出的信封字符串。"""
    if box is None:
        raise PushChannelSecretError("推送渠道加密密钥未配置，无法读取渠道凭据")
    try:
        envelope = json.loads(encrypted_config)
    except json.JSONDecodeError as exc:
        raise PushChannelSecretError("渠道凭据信封损坏") from exc
    try:
        plaintext = box.unseal(envelope)
    except WeChatSecretBoxError as exc:
        raise PushChannelSecretError("渠道凭据解密失败") from exc
    try:
        config = json.loads(plaintext)
    except json.JSONDecodeError as exc:
        raise PushChannelSecretError("渠道凭据内容损坏") from exc
    if not isinstance(config, dict):
        raise PushChannelSecretError("渠道凭据内容损坏")
    return config
