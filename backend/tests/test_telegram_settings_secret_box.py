"""build_telegram_settings_secret_box 密钥解析顺序的契约测试。

钉住的对外语义：
- TELEGRAM_CONFIG_ENCRYPTION_KEY 显式配置时优先使用（专用密钥隔离）；
- 未配置时回落复用 PUSH_CHANNEL_ENCRYPTION_KEY（推送部署已就位，免新增 env）；
- 两者皆无 → None（写 secret fail-closed，绝不明文落库）；
- 显式配置但非法 → None 且不静默回落（运维必须发现配置错误）。
"""

from __future__ import annotations

import base64
import os
from types import SimpleNamespace

from backend.app.repositories.postgres_telegram_settings_repository import (
    build_telegram_settings_secret_box,
)

_KEY_A = base64.urlsafe_b64encode(os.urandom(32)).decode()
_KEY_B = base64.urlsafe_b64encode(os.urandom(32)).decode()


def _config(**overrides):
    values = {
        "telegram_config_encryption_key": "",
        "telegram_config_encryption_key_version": "v1",
        "push_channel_encryption_key": "",
        "push_channel_encryption_key_version": "v1",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_explicit_telegram_key_wins() -> None:
    box = build_telegram_settings_secret_box(
        config=_config(
            telegram_config_encryption_key=_KEY_A,
            push_channel_encryption_key=_KEY_B,
        )
    )
    assert box is not None
    # 用专用密钥可解，用回落密钥不可解 → 证明生效的是显式密钥
    envelope = box.seal("secret")
    fallback_box = build_telegram_settings_secret_box(
        config=_config(push_channel_encryption_key=_KEY_B)
    )
    assert fallback_box is not None
    try:
        fallback_box.unseal(envelope)
    except Exception:
        return
    raise AssertionError("fallback key must not unseal explicit-key ciphertext")


def test_falls_back_to_push_channel_key() -> None:
    box = build_telegram_settings_secret_box(
        config=_config(push_channel_encryption_key=_KEY_B)
    )
    assert box is not None
    assert box.unseal(box.seal("secret")) == "secret"


def test_no_key_returns_none() -> None:
    assert build_telegram_settings_secret_box(config=_config()) is None


def test_invalid_explicit_key_does_not_fall_back() -> None:
    box = build_telegram_settings_secret_box(
        config=_config(
            telegram_config_encryption_key="not-base64!!!",
            push_channel_encryption_key=_KEY_B,
        )
    )
    assert box is None
