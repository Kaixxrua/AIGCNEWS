from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from backend.app.core.operations import ApplicationOperationsRuntime
from backend.app.repositories.wechat_account_repository import (
    WeChatOfficialAccountRepository,
)
from backend.app.repositories.wechat_article_repository import WeChatArticleRepository
from backend.app.repositories.wechat_session_repository import WeChatSessionRepository
from backend.app.services.wechat.errors import (
    WeChatAuthRequired,
    WeChatSessionExpired,
    WeChatSyncRunning,
    WeChatUpstreamError,
)
from backend.app.services.wechat.parser import (
    normalize_article_metadata,
    parse_appmsg_publish_response,
)
from backend.app.services.wechat.transport import WeChatMpTransport

logger = logging.getLogger(__name__)


class WeChatSyncService:
    """Background article metadata synchronization for one official account."""

    def __init__(
        self,
        account_repository: WeChatOfficialAccountRepository,
        article_repository: WeChatArticleRepository,
        session_repository: WeChatSessionRepository,
        transport: WeChatMpTransport,
        operations_runtime: ApplicationOperationsRuntime,
        *,
        max_pages: int = 20,
        max_articles: int = 500,
        inter_page_delay_seconds: float = 1.0,
    ) -> None:
        self._accounts = account_repository
        self._articles = article_repository
        self._sessions = session_repository
        self._transport = transport
        self._operations = operations_runtime
        self._max_pages = max_pages
        self._max_articles = max_articles
        self._inter_page_delay = inter_page_delay_seconds
        self._locks: dict[tuple[int, int], asyncio.Lock] = {}

    def _lock(self, owner_id: int, account_id: int) -> asyncio.Lock:
        key = (owner_id, account_id)
        if key not in self._locks:
            self._locks[key] = asyncio.Lock()
        return self._locks[key]

    async def submit_sync(self, owner_id: int, account_id: int) -> dict[str, Any]:
        account = self._accounts.get_wechat_account(owner_id, account_id)
        if account is None:
            raise WeChatAuthRequired("公众号不存在")
        if account.get("last_sync_status") == "running":
            raise WeChatSyncRunning()

        self._accounts.update_wechat_account_sync_result(
            owner_id,
            account_id,
            {"status": "queued", "message": "等待后台同步"},
        )

        async def _operation() -> None:
            await self._sync_account(owner_id, account_id)

        submitted = self._operations.submit(_operation)
        if not submitted:
            self._accounts.update_wechat_account_sync_result(
                owner_id,
                account_id,
                {"status": "failed", "message": "后台任务队列已关闭"},
            )
            raise WeChatUpstreamError("后台任务队列已关闭")

        return {
            "status": "submitted",
            "account_id": account_id,
            "message": "同步任务已提交",
        }

    async def _sync_account(self, owner_id: int, account_id: int) -> None:
        async with self._lock(owner_id, account_id):
            self._accounts.update_wechat_account_sync_result(
                owner_id,
                account_id,
                {"status": "running", "message": "正在同步"},
            )
            try:
                await self._run_sync(owner_id, account_id)
            except WeChatSessionExpired:
                self._accounts.update_wechat_account_sync_result(
                    owner_id,
                    account_id,
                    {"status": "failed", "message": "微信会话已失效，请重新扫码"},
                )
                raise
            except WeChatAuthRequired:
                self._accounts.update_wechat_account_sync_result(
                    owner_id,
                    account_id,
                    {"status": "failed", "message": "未找到有效微信会话"},
                )
                raise
            except Exception as exc:
                logger.exception("WeChat sync failed for owner=%s account=%s", owner_id, account_id)
                self._accounts.update_wechat_account_sync_result(
                    owner_id,
                    account_id,
                    {"status": "failed", "message": str(exc)},
                )
                raise

    async def _run_sync(self, owner_id: int, account_id: int) -> None:
        session = self._sessions.get_wechat_session(owner_id)
        if session is None:
            raise WeChatAuthRequired()
        if session.get("status") != "active":
            raise WeChatSessionExpired()

        account = self._accounts.get_wechat_account(owner_id, account_id)
        if account is None:
            raise WeChatAuthRequired("公众号不存在")

        fakeid = account["fakeid"]
        cookies = {
            item.strip().split("=", 1)[0]: item.strip().split("=", 1)[1]
            for item in session["cookie"].split(";")
            if "=" in item
        }
        token = session["token"]

        begin = 0
        total_upserted = 0
        for page in range(self._max_pages):
            response = await self._transport.appmsg_publish(
                fakeid=fakeid,
                token=token,
                cookies=cookies,
                begin=begin,
                size=20,
            )
            articles, message_count = parse_appmsg_publish_response(response.json())
            if not articles:
                break

            metadatas = [normalize_article_metadata(a) for a in articles]
            upserted = self._articles.upsert_wechat_articles(
                owner_id,
                account_id,
                metadatas[: self._max_articles - total_upserted],
            )
            total_upserted += upserted

            if message_count == 0:
                break
            begin += message_count
            if total_upserted >= self._max_articles:
                break
            if page < self._max_pages - 1:
                await asyncio.sleep(self._inter_page_delay)

        self._accounts.update_wechat_account_sync_result(
            owner_id,
            account_id,
            {
                "status": "succeeded",
                "message": f"同步完成，新增/更新 {total_upserted} 篇文章",
            },
        )
        self._sessions.save_wechat_session(
            owner_id,
            {
                **session,
                "last_used_at": datetime.now(timezone.utc).isoformat(),
            },
        )
