from __future__ import annotations

import base64

import pytest
from pydantic import ValidationError

from backend.app.core.config import Settings
from backend.app.domain.wechat_secret_box import WeChatSecretBox


def test_valid_wechat_key_round_trips_through_settings() -> None:
    key = WeChatSecretBox.generate_key_material()
    settings = Settings(
        _env_file=None,
        wechat_session_encryption_key=key,
        wechat_session_encryption_key_version="v2",
    )

    box = WeChatSecretBox.from_urlsafe_base64(
        settings.wechat_session_encryption_key,
        settings.wechat_session_encryption_key_version,
    )
    assert box.seal("plain")["v"] == "v2"


def test_empty_wechat_key_is_allowed_but_box_creation_fails() -> None:
    settings = Settings(_env_file=None, wechat_session_encryption_key="")

    assert settings.wechat_session_encryption_key == ""
    with pytest.raises(Exception):
        WeChatSecretBox.from_urlsafe_base64(
            settings.wechat_session_encryption_key,
            settings.wechat_session_encryption_key_version,
        )


def test_settings_rejects_placeholder_wechat_key() -> None:
    with pytest.raises(ValidationError, match="example placeholder"):
        Settings(_env_file=None, wechat_session_encryption_key="CHANGEME123")


def test_settings_rejects_blank_key_version() -> None:
    with pytest.raises(ValidationError, match="key_version"):
        Settings(
            _env_file=None,
            wechat_session_encryption_key_version="",
        )


def test_settings_rejects_long_key_version() -> None:
    with pytest.raises(ValidationError, match="key_version"):
        Settings(
            _env_file=None,
            wechat_session_encryption_key_version="a" * 65,
        )


def test_settings_rejects_invalid_base64_key() -> None:
    settings = Settings(
        _env_file=None,
        wechat_session_encryption_key="not-valid-base64!!!",
    )
    with pytest.raises(Exception):
        WeChatSecretBox.from_urlsafe_base64(
            settings.wechat_session_encryption_key,
            settings.wechat_session_encryption_key_version,
        )


def test_settings_rejects_short_key() -> None:
    settings = Settings(
        _env_file=None,
        wechat_session_encryption_key=base64.urlsafe_b64encode(b"short").decode("ascii"),
    )
    with pytest.raises(Exception):
        WeChatSecretBox.from_urlsafe_base64(
            settings.wechat_session_encryption_key,
            settings.wechat_session_encryption_key_version,
        )
