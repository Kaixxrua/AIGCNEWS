from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from backend.app.core.operations import ApplicationOperationsRuntime
from backend.app.repositories.wechat_account_repository import (
    WeChatOfficialAccountRepository,
)
from backend.app.repositories.wechat_article_repository import WeChatArticleRepository
from backend.app.repositories.wechat_session_repository import WeChatSessionRepository
from backend.app.services.wechat.errors import (
    WeChatAuthRequired,
    WeChatRateLimited,
    WeChatSessionExpired,
    WeChatSyncRunning,
    WeChatUpstreamError,
)
from backend.app.services.wechat.parser import (
    normalize_article_metadata,
    parse_appmsg_publish_response,
)
from backend.app.services.wechat.transport import WeChatMpTransport
from backend.app.services.wechat_sogou.parser import (
    extract_article_identity,
    normalize_account_name,
    parse_article_search_page,
)
from backend.app.services.wechat_sogou.transport import SogouWechatTransport

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
        sogou_transport: SogouWechatTransport | None = None,
        sogou_max_pages: int = 2,
        sogou_max_articles: int = 20,
        sogou_request_delay_seconds: float = 1.5,
    ) -> None:
        self._accounts = account_repository
        self._articles = article_repository
        self._sessions = session_repository
        self._transport = transport
        self._operations = operations_runtime
        self._max_pages = max_pages
        self._max_articles = max_articles
        self._inter_page_delay = inter_page_delay_seconds
        self._sogou = sogou_transport
        self._sogou_max_pages = sogou_max_pages
        self._sogou_max_articles = sogou_max_articles
        self._sogou_delay = sogou_request_delay_seconds
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

        cookies = {
            item.strip().split("=", 1)[0]: item.strip().split("=", 1)[1]
            for item in session["cookie"].split(";")
            if "=" in item
        }
        token = session["token"]

        try:
            total_upserted = await self._sync_via_mp_admin(account, cookies, token)
            message = f"同步完成，新增/更新 {total_upserted} 篇文章"
        except WeChatRateLimited:
            if self._sogou is None:
                raise
            logger.info(
                "MP admin article list rate-limited, falling back to Sogou public index: owner=%s account=%s",
                owner_id,
                account_id,
            )
            total_upserted = await self._sync_via_sogou(account)
            message = (
                f"公众号后台接口受限，已通过搜狗公开索引同步 {total_upserted} 篇"
                "（搜狗仅收录近期文章）"
            )

        self._accounts.update_wechat_account_sync_result(
            owner_id,
            account_id,
            {"status": "succeeded", "message": message},
        )
        self._sessions.save_wechat_session(
            owner_id,
            {
                **session,
                "last_used_at": datetime.now(timezone.utc).isoformat(),
            },
        )

    async def _sync_via_mp_admin(
        self,
        account: dict[str, Any],
        cookies: dict[str, str],
        token: str,
    ) -> int:
        fakeid = account["fakeid"]
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
                account["owner_id"],
                account["id"],
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
        return total_upserted

    async def _sync_via_sogou(self, account: dict[str, Any]) -> int:
        """Fetch recent articles from the Sogou WeChat public index.

        Used when the MP admin article-list endpoint is capability-restricted
        (ret=200013). Sogou only indexes recent articles, so this is a
        best-effort fallback, not a full history sync.
        """
        assert self._sogou is not None
        nickname = str(account["nickname"])
        target_name = normalize_account_name(nickname)
        fakeid = account["fakeid"]
        search_referer = (
            "https://weixin.sogou.com/weixin?type=2&query="
            + httpx.QueryParams({"query": nickname})["query"]
        )

        matched: list[dict[str, Any]] = []
        seen_links: set[str] = set()
        for page in range(1, self._sogou_max_pages + 1):
            response = await self._sogou.search_articles(nickname, page=page)
            items = parse_article_search_page(response.text())
            if not items:
                break
            for item in items:
                if item["link_path"] in seen_links:
                    continue
                if normalize_account_name(item["account_name"]) != target_name:
                    continue
                seen_links.add(item["link_path"])
                matched.append(item)
            if len(matched) >= self._sogou_max_articles:
                break
            if page < self._sogou_max_pages:
                await asyncio.sleep(self._sogou_delay)

        metadatas: list[dict[str, Any]] = []
        for item in matched[: self._sogou_max_articles]:
            signed_url = await self._sogou.resolve_article_url(
                item["link_path"], referer=search_referer
            )
            article_page = await self._sogou.fetch_article_page(signed_url)
            identity = extract_article_identity(article_page.text())
            # Cross-source identity check: the article page's biz must match
            # the account fakeid whenever Sogou attributes it to the account.
            if identity["biz"] and identity["biz"] != fakeid:
                logger.info(
                    "Sogou attribution mismatch for %r: biz=%s != fakeid=%s, skipped",
                    item["title"],
                    identity["biz"],
                    fakeid,
                )
                continue
            metadatas.append(
                normalize_article_metadata(
                    {
                        "appmsgid": identity["mid"] or None,
                        "itemidx": int(identity["idx"] or 1),
                        "title": identity["msg_title"] or item["title"],
                        "digest": item["summary"],
                        "author": identity["nickname"] or nickname,
                        "link": signed_url,
                        "cover": item["cover_url"],
                        "create_time": item["published_ts"],
                        "sogou_source": True,
                        "sogou_user_name": identity["user_name"],
                    }
                )
            )
            await asyncio.sleep(self._sogou_delay)

        if not metadatas:
            return 0
        return self._articles.upsert_wechat_articles(
            account["owner_id"],
            account["id"],
            metadatas,
        )
