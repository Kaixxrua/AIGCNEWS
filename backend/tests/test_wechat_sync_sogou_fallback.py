from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from backend.app.services.wechat.sync_service import WeChatSyncService
from backend.app.services.wechat.transport import WeChatUpstreamResponse

FIXTURES = Path(__file__).parent / "fixtures" / "wechat_sogou"


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _rate_limited_publish_response() -> WeChatUpstreamResponse:
    headers = MagicMock()
    headers.get_list.return_value = []
    return WeChatUpstreamResponse(
        status_code=200,
        headers=headers,
        content=b'{"base_resp":{"ret":200013,"err_msg":"freq control"}}',
        cookies={},
    )


def _make_service(*, with_sogou: bool = True):
    accounts = MagicMock()
    articles = MagicMock()
    sessions = MagicMock()
    transport = MagicMock()
    operations = MagicMock()
    sogou = MagicMock() if with_sogou else None
    service = WeChatSyncService(
        accounts,
        articles,
        sessions,
        transport,
        operations,
        sogou_transport=sogou,
        sogou_request_delay_seconds=0,
    )
    return service, accounts, articles, sessions, transport, sogou


def _prime_session_and_account(sessions: MagicMock, accounts: MagicMock) -> None:
    sessions.get_wechat_session.return_value = {
        "status": "active",
        "token": "tok",
        "cookie": "slave_sid=abc",
    }
    accounts.get_wechat_account.return_value = {
        "id": 1,
        "owner_id": 3,
        "fakeid": "Mzk1NzE0NDcyNg==",
        "nickname": "Ai迷思录",
    }


def test_sync_falls_back_to_sogou_on_rate_limit() -> None:
    service, accounts, articles, sessions, transport, sogou = _make_service()
    _prime_session_and_account(sessions, accounts)
    transport.appmsg_publish = AsyncMock(return_value=_rate_limited_publish_response())
    sogou.search_articles = AsyncMock(
        side_effect=[
            MagicMock(text=MagicMock(return_value=_fixture("search_page.html"))),
            MagicMock(text=MagicMock(return_value="<html>no more</html>")),
        ]
    )
    sogou.resolve_article_url = AsyncMock(
        return_value="https://mp.weixin.qq.com/s?src=11&signature=abc"
    )
    sogou.fetch_article_page = AsyncMock(
        return_value=MagicMock(text=MagicMock(return_value=_fixture("article_page.html")))
    )
    articles.upsert_wechat_articles.return_value = 3

    asyncio.run(service._run_sync(3, 1))

    sogou.search_articles.assert_awaited()
    assert sogou.resolve_article_url.await_count == 3
    metadatas = articles.upsert_wechat_articles.call_args[0][2]
    assert len(metadatas) == 3
    assert metadatas[0]["stable_article_key"] == "2247483765-1"
    assert metadatas[0]["message_id"] == "2247483765"
    assert metadatas[0]["title"] == "如何快速入门AI安全领域?"
    result = accounts.update_wechat_account_sync_result.call_args[0][2]
    assert result["status"] == "succeeded"
    assert "搜狗" in result["message"]


def test_sync_skips_articles_with_mismatched_biz() -> None:
    service, accounts, articles, sessions, transport, sogou = _make_service()
    _prime_session_and_account(sessions, accounts)
    transport.appmsg_publish = AsyncMock(return_value=_rate_limited_publish_response())
    sogou.search_articles = AsyncMock(
        return_value=MagicMock(text=MagicMock(return_value=_fixture("search_page.html")))
    )
    sogou.resolve_article_url = AsyncMock(
        return_value="https://mp.weixin.qq.com/s?src=11&signature=abc"
    )
    # Article page whose biz belongs to a different account.
    wrong_biz_page = _fixture("article_page.html").replace(
        'var biz = "Mzk1NzE0NDcyNg==";', 'var biz = "AAAAAAAAAAAAAA==";'
    )
    sogou.fetch_article_page = AsyncMock(
        return_value=MagicMock(text=MagicMock(return_value=wrong_biz_page))
    )

    asyncio.run(service._run_sync(3, 1))

    articles.upsert_wechat_articles.assert_not_called()
    result = accounts.update_wechat_account_sync_result.call_args[0][2]
    assert "0 篇" in result["message"]


def test_sync_reraises_rate_limit_without_sogou_transport() -> None:
    service, accounts, articles, sessions, transport, _ = _make_service(with_sogou=False)
    _prime_session_and_account(sessions, accounts)
    transport.appmsg_publish = AsyncMock(return_value=_rate_limited_publish_response())

    import pytest

    with pytest.raises(Exception, match="限流"):
        asyncio.run(service._run_sync(3, 1))
