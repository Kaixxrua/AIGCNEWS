from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from backend.app.services.wechat.errors import (
    WeChatAccountContextError,
    WeChatLoginFailed,
    WeChatQrExpired,
    WeChatSessionExpired,
)
from backend.app.services.wechat.login_service import WeChatLoginService, _session_to_summary
from backend.app.services.wechat.transport import WeChatUpstreamResponse


def _fake_response(
    content: bytes = b'{"base_resp":{"ret":0}}',
    cookies: dict[str, str] | None = None,
) -> WeChatUpstreamResponse:
    headers = MagicMock()
    headers.get_list.return_value = []
    return WeChatUpstreamResponse(
        status_code=200,
        headers=headers,
        content=content,
        cookies=cookies or {},
    )


def _fake_home_response(html: str = "", status_code: int = 200) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.text = MagicMock(return_value=html)
    response.cookies = {}
    return response


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


def test_complete_login_returns_existing_session_when_already_completed() -> None:
    service, attempts, sessions, transport = _make_service()
    attempts.get_login_attempt.return_value = {
        "status": "completed",
        "uuid_cookie": "uuid=abc",
        "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
    }
    sessions.get_wechat_session.return_value = {
        "status": "active",
        "account_name": "Test",
    }

    summary = asyncio.run(service.complete_login(1, uuid4()))

    assert summary["connected"] is True
    transport.biz_login.assert_not_called()


def test_complete_login_validates_session_and_saves_account_info() -> None:
    service, attempts, sessions, transport = _make_service()
    attempts.get_login_attempt.return_value = {
        "status": "confirmed",
        "uuid_cookie": "uuid=abc123",
        "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
    }
    transport.biz_login = AsyncMock(
        return_value=_fake_response(
            b'{"base_resp":{"ret":0},"redirect_url":"/cgi-bin/home?token=9876543210"}',
            cookies={"slave_sid": "session-sid", "slave_user": "gh_abc"},
        )
    )
    transport.fetch_home_page = AsyncMock(
        return_value=_fake_home_response(
            'wx.cgiData.nick_name = "AdminAccount"; wx.cgiData.head_img = "https://x.png";'
        )
    )
    # Mirror the real Postgres repository contract: token and cookie are
    # mandatory on every save, so a metadata-only payload must fail here
    # instead of slipping through to production (regression for the 500
    # caused by a partial second save in complete_login).
    saved_payloads: list[dict] = []

    def _save_session(owner_id: int, payload: dict) -> dict:
        if not payload.get("token") or not payload.get("cookie"):
            raise ValueError("token and cookie are required")
        saved_payloads.append(payload)
        return {
            "status": payload.get("status", "active"),
            "account_name": payload.get("account_name", ""),
            "account_avatar_url": payload.get("account_avatar_url", ""),
        }

    sessions.save_wechat_session.side_effect = _save_session

    summary = asyncio.run(service.complete_login(1, uuid4()))

    transport.fetch_home_page.assert_called_once()
    _, kwargs = transport.fetch_home_page.call_args
    assert kwargs["token"] == "9876543210"
    assert "uuid" not in kwargs["cookies"]
    assert len(saved_payloads) == 2
    assert saved_payloads[1]["token"] == "9876543210"
    assert saved_payloads[1]["cookie"]
    assert saved_payloads[1]["account_name"] == "AdminAccount"
    assert summary["account_name"] == "AdminAccount"


def test_complete_login_fails_when_home_page_missing_account_info() -> None:
    service, attempts, sessions, transport = _make_service()
    attempts.get_login_attempt.return_value = {
        "status": "confirmed",
        "uuid_cookie": "uuid=abc123",
        "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
    }
    transport.biz_login = AsyncMock(
        return_value=_fake_response(
            b'{"base_resp":{"ret":0},"redirect_url":"/cgi-bin/home?token=9876543210"}'
        )
    )
    transport.fetch_home_page = AsyncMock(
        return_value=_fake_home_response("<html>system error</html>")
    )
    sessions.save_wechat_session.return_value = {"status": "active", "account_name": ""}

    with pytest.raises(WeChatAccountContextError):
        asyncio.run(service.complete_login(1, uuid4()))

    sessions.mark_wechat_session_invalid.assert_called_once()


def test_complete_login_fails_when_home_page_returns_non_200() -> None:
    service, attempts, sessions, transport = _make_service()
    attempts.get_login_attempt.return_value = {
        "status": "confirmed",
        "uuid_cookie": "uuid=abc123",
        "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
    }
    transport.biz_login = AsyncMock(
        return_value=_fake_response(
            b'{"base_resp":{"ret":0},"redirect_url":"/cgi-bin/home?token=9876543210"}'
        )
    )
    transport.fetch_home_page = AsyncMock(
        return_value=_fake_home_response("", status_code=302)
    )
    sessions.save_wechat_session.return_value = {"status": "active", "account_name": ""}

    with pytest.raises(WeChatSessionExpired):
        asyncio.run(service.complete_login(1, uuid4()))

    sessions.mark_wechat_session_invalid.assert_called_once()
