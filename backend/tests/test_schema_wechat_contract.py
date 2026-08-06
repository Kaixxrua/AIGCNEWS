from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from backend.app.models.schema_wechat import (
    WeChatAccountSaveRequest,
    WeChatArticleResponse,
    WeChatCatalogAccountResponse,
    WeChatCatalogListResponse,
    WeChatFeedAccountEntry,
    WeChatFeedResponse,
    WeChatFollowStateResponse,
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


# ---------------------------------------------------------------------------
# User-facing catalog / follow / feed models
# ---------------------------------------------------------------------------

FORBIDDEN_ACCOUNT_FIELDS = (
    "owner_id",
    "fakeid",
    "token",
    "cookie",
    "last_sync_status",
    "last_sync_message",
    "last_sync_at",
)


def test_catalog_account_response_has_no_admin_internals() -> None:
    response = WeChatCatalogAccountResponse(id=7, nickname="测试号", followed=True)

    data = response.model_dump()
    for field in FORBIDDEN_ACCOUNT_FIELDS:
        assert field not in data
    assert "enabled" not in data
    assert data["followed"] is True


def test_catalog_list_response_wraps_items() -> None:
    response = WeChatCatalogListResponse(
        items=[WeChatCatalogAccountResponse(id=7)],
        total=1,
    )
    data = response.model_dump()
    assert data["total"] == 1
    assert data["items"][0]["id"] == 7
    for field in FORBIDDEN_ACCOUNT_FIELDS:
        assert field not in data["items"][0]


def test_follow_state_response_shape() -> None:
    response = WeChatFollowStateResponse(account_id=7, followed=False)
    assert response.model_dump() == {"account_id": 7, "followed": False}


def test_feed_response_has_no_admin_internals() -> None:
    entry = WeChatFeedAccountEntry(
        account=WeChatCatalogAccountResponse(id=7, nickname="测试号", followed=True),
        articles=[
            WeChatArticleResponse(
                id=1,
                account_id=7,
                stable_article_key="k1",
                title="文章",
            )
        ],
    )
    response = WeChatFeedResponse(items=[entry], per_account=5)

    data = response.model_dump()
    assert data["per_account"] == 5
    account_data = data["items"][0]["account"]
    for field in FORBIDDEN_ACCOUNT_FIELDS:
        assert field not in account_data
    article_data = data["items"][0]["articles"][0]
    assert "raw_metadata" not in article_data


def test_feed_account_entry_articles_default_empty() -> None:
    entry = WeChatFeedAccountEntry(
        account=WeChatCatalogAccountResponse(id=7),
    )
    assert entry.articles == []
