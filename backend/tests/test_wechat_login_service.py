from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from backend.app.services.wechat.errors import WeChatLoginFailed, WeChatQrExpired
from backend.app.services.wechat.login_service import WeChatLoginService, _session_to_summary
from backend.app.services.wechat.transport import WeChatUpstreamResponse


def _fake_response(content: bytes = b'{"base_resp":{"ret":0}}') -> WeChatUpstreamResponse:
    headers = MagicMock()
    headers.get_list.return_value = []
    return WeChatUpstreamResponse(
        status_code=200,
        headers=headers,
        content=content,
        cookies={},
    )


def _make_service() -> tuple[WeChatLoginService, MagicMock, MagicMock, MagicMock]:
    attempts = MagicMock()
    sessions = MagicMock()
    transport = MagicMock()
    service = WeChatLoginService(attempts, sessions, transport)
    return service, attempts, sessions, transport


def test_session_summary_hides_secrets() -> None:
    summary = _session_to_summary(
        {
            "status": "active",
            "token": "secret",
            "cookie": "secret",
            "account_name": "Test",
        }
    )
    assert summary["connected"] is True
    assert "token" not in summary
    assert "cookie" not in summary


def test_start_login_attempt_stores_encrypted_attempt() -> None:
    service, attempts, _, transport = _make_service()
    headers = MagicMock()
    headers.get_list.return_value = ["uuid=abc123; Path=/"]
    transport.start_login = AsyncMock(
        return_value=WeChatUpstreamResponse(
            status_code=200,
            headers=headers,
            content=b'{"base_resp":{"ret":0}}',
            cookies={"uuid": "abc123"},
        )
    )
    attempts.create_login_attempt.return_value = {
        "attempt_id": uuid4(),
        "status": "waiting_scan",
        "expires_at": datetime.now(timezone.utc).isoformat(),
    }

    result = asyncio.run(service.start_login_attempt(1))

    assert "attempt_id" in result
    assert transport.start_login.called
    attempts.create_login_attempt.assert_called_once()
    stored = attempts.create_login_attempt.call_args[0][2]
    assert "uuid_cookie" in stored


def test_get_qr_code_requires_valid_attempt() -> None:
    service, attempts, _, transport = _make_service()
    attempts.get_login_attempt.return_value = None

    with pytest.raises(WeChatQrExpired):
        asyncio.run(service.get_qr_code_image(1, uuid4()))


def test_get_qr_code_passes_uuid_cookie() -> None:
    service, attempts, _, transport = _make_service()
    attempts.get_login_attempt.return_value = {
        "uuid_cookie": "uuid=abc123",
        "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
    }
    headers = MagicMock()
    headers.get_list.return_value = []
    transport.get_qr_code = AsyncMock(
        return_value=WeChatUpstreamResponse(
            status_code=200,
            headers=headers,
            content=b"\x89PNG\r\n\x1a\n",
            cookies={},
        )
    )

    content, media_type = asyncio.run(service.get_qr_code_image(1, uuid4()))

    assert content == b"\x89PNG\r\n\x1a\n"
    transport.get_qr_code.assert_called_once()
    _, kwargs = transport.get_qr_code.call_args
    assert kwargs.get("cookies") == {"uuid": "abc123"}


def test_complete_login_fails_when_not_confirmed() -> None:
    service, attempts, _, transport = _make_service()
    attempts.get_login_attempt.return_value = {
        "status": "waiting_scan",
        "uuid_cookie": "uuid=abc",
        "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
    }

    with pytest.raises(WeChatLoginFailed, match="扫码尚未确认"):
        asyncio.run(service.complete_login(1, uuid4()))
