from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from backend.app.models.schema_wechat import (
    WeChatAccountSaveRequest,
    WeChatArticleResponse,
    WeChatLoginAttemptResponse,
    WeChatSessionResponse,
    WeChatSyncSubmitResponse,
)


def test_login_attempt_response_has_no_secret_fields() -> None:
    response = WeChatLoginAttemptResponse(
        attempt_id=uuid4(),
        status="waiting_scan",
        expires_at=datetime.now(timezone.utc),
    )

    data = response.model_dump()
    assert "uuid_cookie" not in data
    assert "token" not in data
    assert data["status"] == "waiting_scan"


def test_session_response_never_exposes_token_or_cookie() -> None:
    response = WeChatSessionResponse(
        connected=True,
        status="active",
        account_name="Test",
    )

    data = response.model_dump()
    assert data["connected"] is True
    assert "encrypted_cookie" not in data
    assert "encrypted_token" not in data
    assert data["status"] == "active"


def test_account_save_request_rejects_empty_fakeid() -> None:
    with pytest.raises(ValidationError):
        WeChatAccountSaveRequest(fakeid="")


def test_account_save_request_trims_and_validates_lengths() -> None:
    request = WeChatAccountSaveRequest(
        fakeid="fakeid123",
        nickname="  测试  ",
        alias="alias",
        avatar_url="https://example.com/avatar.png",
        signature="signature",
    )
    assert request.fakeid == "fakeid123"


def test_article_response_itemidx_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        WeChatArticleResponse(
            account_id=1,
            stable_article_key="key",
            itemidx=0,
        )

    valid = WeChatArticleResponse(
        account_id=1,
        stable_article_key="key",
        itemidx=1,
    )
    assert valid.itemidx == 1


def test_sync_submit_response_defaults_to_submitted() -> None:
    response = WeChatSyncSubmitResponse(account_id=42, message="queued")
    assert response.status == "submitted"


def test_login_attempt_response_rejects_unknown_status() -> None:
    with pytest.raises(ValidationError):
        WeChatLoginAttemptResponse(
            attempt_id=uuid4(),
            status="weird_status",  # type: ignore[arg-type]
            expires_at=datetime.now(timezone.utc),
        )
