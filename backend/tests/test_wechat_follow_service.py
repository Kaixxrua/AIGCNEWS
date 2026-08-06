from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from backend.app.services.wechat.errors import WeChatAccountNotFound
from backend.app.services.wechat.follow_service import WeChatFollowService


def _service(*, followed_ids: list[int], article: dict | None) -> tuple[WeChatFollowService, MagicMock, MagicMock]:
    follows = MagicMock()
    follows.list_followed_account_ids.return_value = followed_ids
    articles = MagicMock()
    articles.get_wechat_article.return_value = article
    return WeChatFollowService(follows, articles), follows, articles


def test_get_article_detail_returns_body_for_follower() -> None:
    article = {"id": 11, "account_id": 7, "content_html": "<p>正文</p>"}
    service, _, articles = _service(followed_ids=[7], article=article)

    result = service.get_article_detail(1, 7, 11)

    assert result["content_html"] == "<p>正文</p>"
    articles.get_wechat_article.assert_called_once_with(1, 7, 11)


def test_get_article_detail_rejects_non_follower_without_leaking() -> None:
    service, _, articles = _service(followed_ids=[8], article={"id": 11})

    with pytest.raises(WeChatAccountNotFound):
        service.get_article_detail(1, 7, 11)
    # No repository lookup happens past the follow boundary.
    articles.get_wechat_article.assert_not_called()


def test_get_article_detail_missing_article_raises_not_found() -> None:
    service, _, _ = _service(followed_ids=[7], article=None)

    with pytest.raises(WeChatAccountNotFound):
        service.get_article_detail(1, 7, 999)
