from __future__ import annotations

import base64

import pytest

from backend.app.domain.wechat_secret_box import (
    WeChatSecretBox,
    WeChatSecretBoxError,
)


def test_secret_box_round_trip() -> None:
    box = WeChatSecretBox.generate_for_test()
    plaintext = "cookie_wxa_sid=abc123; token=super_secret"

    envelope = box.seal(plaintext)

    assert set(envelope.keys()) == {"v", "ct", "nonce"}
    assert envelope["v"] == "v1"
    assert envelope["ct"] != plaintext
    assert box.unseal(envelope) == plaintext


def test_secret_box_requires_non_empty_key_version() -> None:
    key = base64.urlsafe_b64encode(b"x" * 32).decode("ascii")
    with pytest.raises(WeChatSecretBoxError, match="key_version"):
        WeChatSecretBox.from_urlsafe_base64(key, "")
    with pytest.raises(WeChatSecretBoxError, match="key_version"):
        WeChatSecretBox.from_urlsafe_base64(key, "a" * 65)


def test_secret_box_rejects_missing_key() -> None:
    with pytest.raises(WeChatSecretBoxError, match="key is required"):
        WeChatSecretBox.from_urlsafe_base64("", "v1")


def test_secret_box_rejects_invalid_base64() -> None:
    with pytest.raises(WeChatSecretBoxError, match="not valid base64"):
        WeChatSecretBox.from_urlsafe_base64("!!!not-base64!!!", "v1")


def test_secret_box_rejects_wrong_key_length() -> None:
    short = base64.urlsafe_b64encode(b"short").decode("ascii")
    with pytest.raises(WeChatSecretBoxError, match="32 bytes"):
        WeChatSecretBox.from_urlsafe_base64(short, "v1")


def test_secret_box_fails_on_tampered_ciphertext() -> None:
    box = WeChatSecretBox.generate_for_test()
    envelope = box.seal("secret")
    envelope["ct"] = base64.urlsafe_b64encode(b"tampered").decode("ascii")

    with pytest.raises(WeChatSecretBoxError, match="authentication failed"):
        box.unseal(envelope)


def test_secret_box_fails_on_key_version_mismatch() -> None:
    box_v1 = WeChatSecretBox.generate_for_test("v1")
    box_v2 = WeChatSecretBox.generate_for_test("v2")
    envelope = box_v1.seal("secret")

    with pytest.raises(WeChatSecretBoxError, match="key version"):
        box_v2.unseal(envelope)


def test_secret_box_keys_are_independent() -> None:
    key = base64.urlsafe_b64encode(b"x" * 32).decode("ascii")
    box_a = WeChatSecretBox.from_urlsafe_base64(key, "v1")
    box_b = WeChatSecretBox.generate_for_test()
    envelope = box_a.seal("secret")

    with pytest.raises(WeChatSecretBoxError):
        box_b.unseal(envelope)


def test_secret_box_generate_key_material_is_32_bytes() -> None:
    material = WeChatSecretBox.generate_key_material()
    decoded = base64.urlsafe_b64decode(material)
    assert len(decoded) == 32
