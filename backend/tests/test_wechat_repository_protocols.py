from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock

from backend.app.repositories.wechat_account_repository import (
    WeChatOfficialAccountRepository,
)
from backend.app.repositories.wechat_article_repository import WeChatArticleRepository
from backend.app.repositories.wechat_follow_repository import WeChatFollowRepository
from backend.app.repositories.wechat_session_repository import (
    WeChatLoginAttemptRepository,
    WeChatSessionRepository,
)


def test_protocols_define_expected_methods() -> None:
    assert callable(WeChatLoginAttemptRepository.create_login_attempt)
    assert callable(WeChatLoginAttemptRepository.get_login_attempt)
    assert callable(WeChatLoginAttemptRepository.update_login_attempt)
    assert callable(WeChatLoginAttemptRepository.delete_login_attempt)
    assert callable(WeChatLoginAttemptRepository.expire_login_attempts)

    assert callable(WeChatSessionRepository.get_wechat_session)
    assert callable(WeChatSessionRepository.save_wechat_session)
    assert callable(WeChatSessionRepository.mark_wechat_session_invalid)
    assert callable(WeChatSessionRepository.delete_wechat_session)

    assert callable(WeChatOfficialAccountRepository.list_wechat_accounts)
    assert callable(WeChatOfficialAccountRepository.get_wechat_account)
    assert callable(WeChatOfficialAccountRepository.upsert_wechat_account)
    assert callable(WeChatOfficialAccountRepository.update_wechat_account_sync_result)
    assert callable(WeChatOfficialAccountRepository.delete_wechat_account)

    assert callable(WeChatArticleRepository.list_wechat_articles)
    assert callable(WeChatArticleRepository.get_wechat_article)
    assert callable(WeChatArticleRepository.count_wechat_articles)
    assert callable(WeChatArticleRepository.upsert_wechat_articles)
    assert callable(WeChatArticleRepository.list_recent_articles_for_accounts)

    assert callable(WeChatFollowRepository.list_catalog_with_follow_state)
    assert callable(WeChatFollowRepository.get_enabled_catalog_account)
    assert callable(WeChatFollowRepository.follow_account)
    assert callable(WeChatFollowRepository.unfollow_account)
    assert callable(WeChatFollowRepository.list_followed_account_ids)


class FakeDatabase:
    def __init__(self, cursor: MagicMock) -> None:
        self.cursor = cursor
        self.connection = MagicMock()
        cursor_context = MagicMock()
        cursor_context.__enter__.return_value = cursor
        self.connection.cursor.return_value = cursor_context

    @contextmanager
    def transaction(self):
        yield self.connection


# Concrete adapters do not exist in the Contract phase; this placeholder
# ensures the Protocol surface is importable and type-checkable.
class StubLoginAttemptRepository(WeChatLoginAttemptRepository):
    def create_login_attempt(self, owner_id, attempt_id, payload): ...
    def get_login_attempt(self, owner_id, attempt_id): ...
    def update_login_attempt(self, owner_id, attempt_id, payload): ...
    def delete_login_attempt(self, owner_id, attempt_id): ...
    def expire_login_attempts(self, owner_id): ...


def test_stub_adapter_conforms_to_login_attempt_protocol() -> None:
    contract: WeChatLoginAttemptRepository = StubLoginAttemptRepository()
    assert contract.create_login_attempt is not None
    assert contract.expire_login_attempts is not None
