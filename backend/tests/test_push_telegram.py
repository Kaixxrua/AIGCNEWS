"""Telegram 推送：deep-link 绑定服务、Bot API 投递器与路由契约测试。

安全断言要点：
- nonce 只存 SHA-256 哈希，deep-link 原文只在创建响应出现一次；
- chat_id 只存密封配置，API 响应/渠道列表不出现原始 chat_id；
- webhook 对 Telegram 恒回 200（secret 校验失败除外，404 隐藏端点）；
- Bot token 不出现在任何异常文案中。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch
from uuid import UUID

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api import routes_push
from backend.app.api.dependencies import (
    get_push_channel_service,
    get_telegram_link_service,
)
from backend.app.core.auth import RequireUser
from backend.app.core.config import settings as core_settings
from backend.app.domain.wechat_secret_box import WeChatSecretBox
from backend.app.services.push.channel_service import PushChannelService
from backend.app.services.push.errors import (
    ProviderCredentialInvalidError,
    ProviderRateLimitedError,
    TelegramDeliveryError,
    TelegramNotConfiguredError,
)
from backend.app.services.push.secrets import seal_channel_config, unseal_channel_config
from backend.app.services.push.telegram_config_provider import (
    reset_telegram_config_provider,
)
from backend.app.services.push.telegram_service import (
    TelegramBotClient,
    TelegramLinkService,
)
from backend.tests.test_email_service_contracts import FakeRedis
from backend.tests.test_push_channels import FakePushChannelRepository

_TEST_KEY_MATERIAL = base64.urlsafe_b64encode(bytes(range(32))).decode()


def _test_box() -> WeChatSecretBox:
    return WeChatSecretBox.from_urlsafe_base64(_TEST_KEY_MATERIAL, "v1")


def _service_config(**overrides: Any) -> SimpleNamespace:
    values = {
        "telegram_push_enabled": True,
        "telegram_bot_username": "aigc_news_bot",
        "telegram_link_ttl_seconds": 300,
        "telegram_request_timeout_seconds": 5.0,
        "push_channel_encryption_key": _TEST_KEY_MATERIAL,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _member_user(user_id: int = 7) -> dict:
    return {
        "user_id": user_id,
        "email": f"user{user_id}@example.com",
        "role": "user",
        "membership_tier": "member",
    }


class FakeTelegramLinkAttemptRepository:
    def __init__(self) -> None:
        self.rows: dict[UUID, dict] = {}

    def create_attempt(
        self, *, attempt_id, user_id, nonce_hash, expires_at
    ) -> dict:
        row = {
            "attempt_id": attempt_id,
            "user_id": user_id,
            "nonce_hash": nonce_hash,
            "status": "pending",
            "expires_at": expires_at,
            "completed_at": None,
            "channel_id": None,
            "telegram_chat_id": None,
            "created_at": datetime.now(timezone.utc),
        }
        self.rows[attempt_id] = row
        return dict(row)

    def get_attempt(self, *, user_id, attempt_id) -> dict | None:
        row = self.rows.get(attempt_id)
        if row is None or row["user_id"] != user_id:
            return None
        return dict(row)

    def consume_attempt(self, *, nonce_hash, chat_id) -> dict | None:
        now = datetime.now(timezone.utc)
        for row in self.rows.values():
            if (
                row["nonce_hash"] == nonce_hash
                and row["status"] == "pending"
                and row["expires_at"] > now
            ):
                row["status"] = "completed"
                row["completed_at"] = now
                row["telegram_chat_id"] = chat_id
                return dict(row)
        return None

    def attach_channel(self, *, attempt_id, channel_id) -> None:
        row = self.rows.get(attempt_id)
        assert row is not None
        row["channel_id"] = channel_id


class TelegramLinkServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.attempts = FakeTelegramLinkAttemptRepository()
        self.channels = FakePushChannelRepository()
        self.service = TelegramLinkService(
            attempts=self.attempts,
            channels=self.channels,
            config=_service_config(),
            secret_box=_test_box(),
        )

    async def _create_link(self, user: dict | None = None) -> tuple[dict, str]:
        link = await self.service.create_link(user=user or _member_user())
        nonce = link["deep_link"].split("?start=", 1)[1]
        return link, nonce

    async def test_create_link_returns_deep_link_and_stores_only_hash(self) -> None:
        link, nonce = await self._create_link()
        self.assertEqual(link["status"], "pending")
        self.assertTrue(link["deep_link"].startswith("https://t.me/aigc_news_bot?start="))
        self.assertTrue(nonce)
        attempt = self.attempts.rows[UUID(link["attempt_id"])]
        self.assertEqual(
            attempt["nonce_hash"], hashlib.sha256(nonce.encode("utf-8")).hexdigest()
        )
        self.assertNotEqual(attempt["nonce_hash"], nonce)

    async def test_create_link_disabled_raises_not_configured(self) -> None:
        service = TelegramLinkService(
            attempts=self.attempts,
            channels=self.channels,
            config=_service_config(telegram_push_enabled=False),
            secret_box=_test_box(),
        )
        with self.assertRaises(TelegramNotConfiguredError):
            await service.create_link(user=_member_user())

    async def test_create_link_allows_free_user(self) -> None:
        # 简报推送已降级为注册用户免费权益，免费档也可创建绑定链接
        free_user = {**_member_user(), "membership_tier": "free"}
        link = await self.service.create_link(user=free_user)
        self.assertEqual(link["status"], "pending")
        admin = {**_member_user(), "role": "admin", "membership_tier": "free"}
        link = await self.service.create_link(user=admin)
        self.assertEqual(link["status"], "pending")

    async def test_get_link_status_is_owner_scoped(self) -> None:
        link, _nonce = await self._create_link()
        other = await self.service.get_link_status(
            user_id=99, attempt_id=UUID(link["attempt_id"])
        )
        self.assertIsNone(other)
        mine = await self.service.get_link_status(
            user_id=7, attempt_id=UUID(link["attempt_id"])
        )
        assert mine is not None
        self.assertEqual(mine["status"], "pending")
        # 状态查询不回放 deep-link（nonce 已不可重建）
        self.assertEqual(mine["deep_link"], "")

    async def test_get_link_status_marks_expired(self) -> None:
        link, _nonce = await self._create_link()
        row = self.attempts.rows[UUID(link["attempt_id"])]
        row["expires_at"] = datetime.now(timezone.utc) - timedelta(seconds=1)
        mine = await self.service.get_link_status(
            user_id=7, attempt_id=UUID(link["attempt_id"])
        )
        assert mine is not None
        self.assertEqual(mine["status"], "expired")

    async def test_complete_link_creates_verified_channel(self) -> None:
        link, nonce = await self._create_link()
        outcome = await self.service.complete_link(
            nonce=nonce, chat_id="424242001", chat_type="private"
        )
        self.assertEqual(outcome, "ok")
        assert len(self.channels.rows) == 1
        channel = next(iter(self.channels.rows.values()))
        self.assertEqual(channel["user_id"], 7)
        self.assertEqual(channel["channel_type"], "telegram")
        self.assertTrue(channel["verified"])
        config = unseal_channel_config(_test_box(), channel["encrypted_config"])
        self.assertEqual(config["chat_id"], "424242001")
        expected_key = hmac.new(
            _TEST_KEY_MATERIAL.encode("utf-8"),
            b"424242001",
            hashlib.sha256,
        ).hexdigest()
        self.assertEqual(channel["provider_key"], expected_key)
        self.assertNotIn("424242001", channel["target"])
        self.assertEqual(channel["display_target"], "Telegram 私聊 · ****2001")
        attempt = self.attempts.rows[UUID(link["attempt_id"])]
        self.assertEqual(attempt["status"], "completed")
        self.assertEqual(attempt["channel_id"], channel["id"])

    async def test_complete_link_nonce_is_single_use(self) -> None:
        _link, nonce = await self._create_link()
        first = await self.service.complete_link(
            nonce=nonce, chat_id="424242001", chat_type="private"
        )
        second = await self.service.complete_link(
            nonce=nonce, chat_id="424242001", chat_type="private"
        )
        self.assertEqual(first, "ok")
        self.assertEqual(second, "invalid")
        self.assertEqual(len(self.channels.rows), 1)

    async def test_complete_link_expired_attempt_is_invalid(self) -> None:
        link, nonce = await self._create_link()
        row = self.attempts.rows[UUID(link["attempt_id"])]
        row["expires_at"] = datetime.now(timezone.utc) - timedelta(seconds=1)
        outcome = await self.service.complete_link(
            nonce=nonce, chat_id="424242001", chat_type="private"
        )
        self.assertEqual(outcome, "invalid")
        self.assertEqual(len(self.channels.rows), 0)

    async def test_complete_link_ignores_group_chat(self) -> None:
        link, nonce = await self._create_link()
        outcome = await self.service.complete_link(
            nonce=nonce, chat_id="-100123", chat_type="group"
        )
        self.assertEqual(outcome, "ignored")
        self.assertEqual(len(self.channels.rows), 0)
        # 群组消息不消费 nonce，私聊仍可完成绑定
        attempt = self.attempts.rows[UUID(link["attempt_id"])]
        self.assertEqual(attempt["status"], "pending")

    async def test_complete_link_rejects_cross_user_chat_conflict(self) -> None:
        _link, nonce = await self._create_link()
        other_channels = FakePushChannelRepository()
        chat_id = "424242001"
        provider_key = hmac.new(
            _TEST_KEY_MATERIAL.encode("utf-8"), chat_id.encode("utf-8"), hashlib.sha256
        ).hexdigest()
        other_channels.create_channel(
            user_id=99,
            channel_type="telegram",
            target=f"tg:{provider_key[:32]}",
            encrypted_config=seal_channel_config(_test_box(), {"chat_id": chat_id}),
            verified=True,
            provider_key=provider_key,
            display_target="Telegram 私聊 · ****2001",
        )
        service = TelegramLinkService(
            attempts=self.attempts,
            channels=other_channels,
            config=_service_config(),
            secret_box=_test_box(),
        )
        outcome = await service.complete_link(
            nonce=nonce, chat_id=chat_id, chat_type="private"
        )
        self.assertEqual(outcome, "conflict")
        self.assertEqual(len(other_channels.rows), 1)

    async def test_complete_link_rebind_reuses_existing_channel(self) -> None:
        first, nonce1 = await self._create_link()
        self.assertEqual(
            await self.service.complete_link(
                nonce=nonce1, chat_id="424242001", chat_type="private"
            ),
            "ok",
        )
        second, nonce2 = await self._create_link()
        outcome = await self.service.complete_link(
            nonce=nonce2, chat_id="424242001", chat_type="private"
        )
        self.assertEqual(outcome, "ok")
        self.assertEqual(len(self.channels.rows), 1)
        channel_id = next(iter(self.channels.rows))
        self.assertEqual(
            self.attempts.rows[UUID(second["attempt_id"])]["channel_id"], channel_id
        )
        self.assertEqual(
            self.attempts.rows[UUID(first["attempt_id"])]["channel_id"], channel_id
        )


class TelegramBotClientTests(unittest.IsolatedAsyncioTestCase):
    def _client(self, handler) -> tuple[TelegramBotClient, list[httpx.Request]]:
        requests: list[httpx.Request] = []

        def _capture(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return handler(request)

        transport = httpx.MockTransport(_capture)
        return (
            TelegramBotClient(token="secret-token-xyz", transport=transport),
            requests,
        )

    async def test_send_message_chunks_by_byte_budget(self) -> None:
        client, requests = self._client(
            lambda request: httpx.Response(200, json={"ok": True})
        )
        await client.send_message(
            chat_id="424242001", title="标题", content="x" * 3600
        )
        # 超预算内容必须拆成多条顺序发送（确切条数取决于分块器的字节预算）
        self.assertGreaterEqual(len(requests), 2)
        for request in requests:
            self.assertIn("/botsecret-token-xyz/sendMessage", str(request.url))
            self.assertEqual(
                request.headers["User-Agent"], "AIGCNews-Telegram/1.0"
            )

    async def test_send_message_success_single_chunk(self) -> None:
        client, requests = self._client(
            lambda request: httpx.Response(200, json={"ok": True})
        )
        await client.send_message(chat_id="424242001", title="t", content="c")
        self.assertEqual(len(requests), 1)

    async def test_rate_limited_raises_with_retry_after(self) -> None:
        client, _requests = self._client(
            lambda request: httpx.Response(
                429, json={"ok": False, "parameters": {"retry_after": 7}}
            )
        )
        with self.assertRaises(ProviderRateLimitedError) as ctx:
            await client.send_message(chat_id="1", title="t", content="c")
        self.assertIn("7", ctx.exception.detail)
        self.assertNotIn("secret-token-xyz", str(ctx.exception))

    async def test_forbidden_raises_credential_invalid(self) -> None:
        client, _requests = self._client(
            lambda request: httpx.Response(403, json={"ok": False})
        )
        with self.assertRaises(ProviderCredentialInvalidError):
            await client.send_message(chat_id="1", title="t", content="c")

    async def test_server_error_raises_delivery_error(self) -> None:
        client, _requests = self._client(
            lambda request: httpx.Response(500, json={"ok": False})
        )
        with self.assertRaises(TelegramDeliveryError) as ctx:
            await client.send_message(chat_id="1", title="t", content="c")
        self.assertIn("500", ctx.exception.detail)

    async def test_transport_error_never_leaks_token(self) -> None:
        def _boom(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused", request=request)

        client, _requests = self._client(_boom)
        with self.assertRaises(TelegramDeliveryError) as ctx:
            await client.send_message(chat_id="1", title="t", content="c")
        self.assertNotIn("secret-token-xyz", str(ctx.exception))
        self.assertNotIn("secret-token-xyz", ctx.exception.detail)


class FakeTelegramSender:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def send_message(self, *, chat_id: str, title: str, content: str) -> None:
        self.calls.append({"chat_id": chat_id, "title": title, "content": content})


class TelegramTestMessageTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.channels = FakePushChannelRepository()
        self.service = PushChannelService(self.channels)
        row = self.channels.create_channel(
            user_id=7,
            channel_type="telegram",
            target="tg:abc123",
            encrypted_config=seal_channel_config(
                _test_box(), {"chat_id": "424242001"}
            ),
            verified=True,
            provider_key="pk",
            display_target="Telegram 私聊 · ****2001",
        )
        assert row is not None
        self.channel = row

    async def test_send_test_message_uses_sealed_chat_id(self) -> None:
        sender = FakeTelegramSender()
        await self.service.send_test_message(
            user_id=7,
            channel_id=self.channel["id"],
            secret_box=_test_box(),
            telegram_sender=sender,
        )
        self.assertEqual(len(sender.calls), 1)
        self.assertEqual(sender.calls[0]["chat_id"], "424242001")

    async def test_send_test_message_without_sender_raises_not_configured(
        self,
    ) -> None:
        with self.assertRaises(TelegramNotConfiguredError):
            await self.service.send_test_message(
                user_id=7,
                channel_id=self.channel["id"],
                secret_box=_test_box(),
                telegram_sender=None,
            )


class TelegramRouteTests(unittest.TestCase):
    """路由契约：限速、webhook secret 校验与响应脱敏。"""

    def setUp(self) -> None:
        self.redis = FakeRedis()
        self.channels = FakePushChannelRepository()
        self.attempts = FakeTelegramLinkAttemptRepository()
        self.link_service = TelegramLinkService(
            attempts=self.attempts,
            channels=self.channels,
            config=_service_config(),
            secret_box=_test_box(),
        )
        app = FastAPI()
        app.state.redis = self.redis
        app.include_router(routes_push.router, prefix="/api")

        async def user() -> dict:
            return _member_user()

        app.dependency_overrides[RequireUser] = user
        app.dependency_overrides[get_telegram_link_service] = lambda: self.link_service
        app.dependency_overrides[get_push_channel_service] = lambda: (
            PushChannelService(self.channels)
        )
        self.confirmation_sender = FakeTelegramSender()
        reset_telegram_config_provider()
        self.addCleanup(reset_telegram_config_provider)
        self._patchers = [
            patch.object(core_settings, "telegram_push_enabled", True),
            patch.object(
                core_settings, "telegram_webhook_secret", "test-secret"
            ),
            patch.object(
                routes_push,
                "build_telegram_bot_client",
                return_value=self.confirmation_sender,
            ),
            patch.object(
                routes_push,
                "build_push_channel_secret_box",
                side_effect=lambda: _test_box(),
            ),
        ]
        for patcher in self._patchers:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.app = app
        self.client = TestClient(app)

    def _create_link(self) -> tuple[dict, str]:
        response = self.client.post("/api/push/me/channels/telegram/link")
        self.assertEqual(response.status_code, 201, response.text)
        link = response.json()
        nonce = link["deep_link"].split("?start=", 1)[1]
        return link, nonce

    def _webhook_payload(self, *, nonce: str, chat_id: int, chat_type: str) -> dict:
        return {
            "update_id": 1,
            "message": {
                "message_id": 1,
                "text": f"/start {nonce}" if nonce else "/start",
                "chat": {"id": chat_id, "type": chat_type},
            },
        }

    def test_create_link_returns_201_with_deep_link(self) -> None:
        link, nonce = self._create_link()
        self.assertEqual(link["status"], "pending")
        self.assertIn("https://t.me/aigc_news_bot?start=", link["deep_link"])
        self.assertTrue(nonce)

    def test_create_link_free_user_gets_201(self) -> None:
        async def free_user() -> dict:
            return {**_member_user(), "membership_tier": "free"}

        self.app.dependency_overrides[RequireUser] = free_user
        response = self.client.post("/api/push/me/channels/telegram/link")
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["status"], "pending")

    def test_create_link_disabled_gets_503(self) -> None:
        disabled = TelegramLinkService(
            attempts=self.attempts,
            channels=self.channels,
            config=_service_config(telegram_push_enabled=False),
            secret_box=_test_box(),
        )
        self.app.dependency_overrides[get_telegram_link_service] = lambda: disabled
        response = self.client.post("/api/push/me/channels/telegram/link")
        self.assertEqual(response.status_code, 503, response.text)

    def test_get_link_status_owner_only(self) -> None:
        link, _nonce = self._create_link()
        response = self.client.get(
            f"/api/push/me/channels/telegram/link/{link['attempt_id']}"
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "pending")
        self.assertEqual(response.json()["deep_link"], "")

        async def other_user() -> dict:
            return _member_user(user_id=99)

        self.app.dependency_overrides[RequireUser] = other_user
        response = self.client.get(
            f"/api/push/me/channels/telegram/link/{link['attempt_id']}"
        )
        self.assertEqual(response.status_code, 404, response.text)

    def test_get_link_status_rejects_malformed_uuid(self) -> None:
        response = self.client.get("/api/push/me/channels/telegram/link/not-a-uuid")
        self.assertEqual(response.status_code, 404, response.text)

    def test_webhook_hidden_without_secret_configuration(self) -> None:
        with patch.object(core_settings, "telegram_webhook_secret", ""):
            response = self.client.post(
                "/api/push/providers/telegram/webhook",
                json=self._webhook_payload(nonce="x", chat_id=1, chat_type="private"),
                headers={"X-Telegram-Bot-Api-Secret-Token": "test-secret"},
            )
        self.assertEqual(response.status_code, 404, response.text)

    def test_webhook_rejects_wrong_secret(self) -> None:
        response = self.client.post(
            "/api/push/providers/telegram/webhook",
            json=self._webhook_payload(nonce="x", chat_id=1, chat_type="private"),
            headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"},
        )
        self.assertEqual(response.status_code, 404, response.text)

    def test_webhook_private_start_completes_binding(self) -> None:
        link, nonce = self._create_link()
        response = self.client.post(
            "/api/push/providers/telegram/webhook",
            json=self._webhook_payload(
                nonce=nonce, chat_id=424242001, chat_type="private"
            ),
            headers={"X-Telegram-Bot-Api-Secret-Token": "test-secret"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {"ok": True})
        self.assertEqual(len(self.channels.rows), 1)
        # 绑定成功确认消息 best-effort 发送
        self.assertEqual(len(self.confirmation_sender.calls), 1)
        self.assertEqual(self.confirmation_sender.calls[0]["chat_id"], "424242001")
        status_response = self.client.get(
            f"/api/push/me/channels/telegram/link/{link['attempt_id']}"
        )
        self.assertEqual(status_response.json()["status"], "completed")

    def test_webhook_group_chat_ignored(self) -> None:
        _link, nonce = self._create_link()
        response = self.client.post(
            "/api/push/providers/telegram/webhook",
            json=self._webhook_payload(nonce=nonce, chat_id=-100123, chat_type="group"),
            headers={"X-Telegram-Bot-Api-Secret-Token": "test-secret"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {"ok": True})
        self.assertEqual(len(self.channels.rows), 0)
        self.assertEqual(len(self.confirmation_sender.calls), 0)

    def test_webhook_unknown_nonce_still_200(self) -> None:
        response = self.client.post(
            "/api/push/providers/telegram/webhook",
            json=self._webhook_payload(
                nonce="unknown-nonce", chat_id=424242001, chat_type="private"
            ),
            headers={"X-Telegram-Bot-Api-Secret-Token": "test-secret"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(self.channels.rows), 0)
        self.assertEqual(len(self.confirmation_sender.calls), 0)

    def test_webhook_non_message_update_is_noop(self) -> None:
        response = self.client.post(
            "/api/push/providers/telegram/webhook",
            json={"update_id": 1},
            headers={"X-Telegram-Bot-Api-Secret-Token": "test-secret"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(self.channels.rows), 0)

    def test_channel_listing_masks_raw_chat_id(self) -> None:
        _link, nonce = self._create_link()
        self.client.post(
            "/api/push/providers/telegram/webhook",
            json=self._webhook_payload(
                nonce=nonce, chat_id=424242001, chat_type="private"
            ),
            headers={"X-Telegram-Bot-Api-Secret-Token": "test-secret"},
        )
        response = self.client.get("/api/push/me/channels")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertNotIn("424242001", response.text)
        payload = response.json()
        self.assertEqual(payload[0]["channel_type"], "telegram")
        self.assertEqual(payload[0]["target"], "Telegram 私聊 · ****2001")


if __name__ == "__main__":
    unittest.main()
