"""Webhook 推送渠道：URL 识别与 SSRF 防护、载荷/分块、服务与路由契约测试。"""

from __future__ import annotations

import asyncio
import base64
import json
import socket
import unittest
from datetime import date, datetime, timezone
from typing import Any
from unittest.mock import patch

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api import routes_push
from backend.app.api.dependencies import (
    get_push_channel_service,
    get_user_subscription_service,
)
from backend.app.core.auth import RequireUser
from backend.app.domain.wechat_secret_box import WeChatSecretBox
from backend.app.models.schema_push import CreatePushChannelRequest
from backend.app.services.email_service import EmailService
from backend.app.services.push.channel_service import (
    PushChannelService,
)
from backend.app.services.push.dispatch_service import SubscriptionDispatchService
from backend.app.services.push.errors import (
    PushChannelDisabledError,
    PushChannelDuplicateError,
    PushChannelNotVerifiedError,
    WebhookDeliveryError,
    WebhookProbeFailedError,
    WebhookUrlError,
)
from backend.app.services.push.secrets import (
    PushChannelSecretError,
    seal_channel_config,
    unseal_channel_config,
)
from backend.app.services.push.subscription_service import UserSubscriptionService
from backend.app.services.push.webhook_service import (
    MAX_CHUNKS,
    WebhookSender,
    build_webhook_payload,
    chunk_markdown_for_provider,
    detect_provider,
    validate_webhook_url,
)
from backend.tests.test_email_service_contracts import FakeRedis
from backend.tests.test_push_channels import (
    FakePushChannelRepository,
    FakeUserSubscriptionRepository,
)

_NOW = datetime(2026, 8, 6, 8, 0, tzinfo=timezone.utc)
_WECOM_URL = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=test-key-123"
_GENERIC_URL = "https://hooks.example.com/incoming/abc"

_TEST_KEY_MATERIAL = base64.urlsafe_b64encode(bytes(range(32))).decode()


def _test_box() -> WeChatSecretBox:
    return WeChatSecretBox.from_urlsafe_base64(_TEST_KEY_MATERIAL, "v1")


def _public_getaddrinfo(host: str, port: Any) -> list[tuple]:
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port or 0))]


def _private_getaddrinfo(host: str, port: Any) -> list[tuple]:
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.10", port or 0))]


class FakeWebhookSender:
    def __init__(self, *, fail: bool = False) -> None:
        self.calls: list[dict[str, Any]] = []
        self._fail = fail

    async def send(self, *, url: str, title: str, content: str) -> None:
        self.calls.append({"url": url, "title": title, "content": content})
        if self._fail:
            raise WebhookDeliveryError("Webhook 返回 HTTP 500")


class ProviderDetectionTests(unittest.TestCase):
    def test_known_hosts_map_to_platforms(self) -> None:
        cases = {
            "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=k": "wecom",
            "https://oapi.dingtalk.com/robot/send?access_token=t": "dingtalk",
            "https://open.feishu.cn/open-apis/bot/v2/hook/h": "lark",
            "https://open.larksuite.com/open-apis/bot/v2/hook/h": "lark",
            "https://hooks.slack.com/services/T/B/x": "generic",
        }
        for url, expected in cases.items():
            with self.subTest(url=url):
                self.assertEqual(detect_provider(url), expected)


class WebhookUrlValidationTests(unittest.TestCase):
    def test_rejects_non_https(self) -> None:
        with self.assertRaises(WebhookUrlError):
            validate_webhook_url("http://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=k")

    def test_rejects_userinfo_and_empty(self) -> None:
        with self.assertRaises(WebhookUrlError):
            validate_webhook_url("https://user:pass@example.com/hook")
        with self.assertRaises(WebhookUrlError):
            validate_webhook_url("   ")
        with self.assertRaises(WebhookUrlError):
            validate_webhook_url("https://example.com/" + "x" * 2100)

    def test_rejects_private_ip_literals(self) -> None:
        for url in (
            "https://127.0.0.1/hook",
            "https://10.0.0.8/hook",
            "https://192.168.1.1/hook",
            "https://169.254.169.254/latest/meta-data",
        ):
            with self.subTest(url=url):
                with self.assertRaises(WebhookUrlError):
                    validate_webhook_url(url)

    def test_accepts_public_ip_literal_without_dns(self) -> None:
        self.assertEqual(
            validate_webhook_url("https://93.184.216.34/hook"),
            "https://93.184.216.34/hook",
        )

    def test_dns_resolution_must_be_public(self) -> None:
        with patch(
            "backend.app.services.push.webhook_service.socket.getaddrinfo",
            side_effect=_private_getaddrinfo,
        ):
            with self.assertRaises(WebhookUrlError):
                validate_webhook_url(_WECOM_URL)
        with patch(
            "backend.app.services.push.webhook_service.socket.getaddrinfo",
            side_effect=socket.gaierror("name or service not known"),
        ):
            with self.assertRaises(WebhookUrlError):
                validate_webhook_url(_WECOM_URL)

    def test_accepts_public_dns_and_strips_whitespace(self) -> None:
        with patch(
            "backend.app.services.push.webhook_service.socket.getaddrinfo",
            side_effect=_public_getaddrinfo,
        ):
            self.assertEqual(validate_webhook_url(f"  {_WECOM_URL}  "), _WECOM_URL)


class PayloadBuilderTests(unittest.TestCase):
    def test_wecom_markdown_embeds_title(self) -> None:
        payload = build_webhook_payload("wecom", title="标题", content="正文")
        self.assertEqual(payload["msgtype"], "markdown")
        self.assertEqual(payload["markdown"]["content"], "## 标题\n\n正文")

    def test_dingtalk_markdown_carries_title_field(self) -> None:
        payload = build_webhook_payload("dingtalk", title="标题", content="正文")
        self.assertEqual(payload["markdown"]["title"], "标题")
        self.assertIn("正文", payload["markdown"]["text"])

    def test_lark_plain_text(self) -> None:
        payload = build_webhook_payload("lark", title="标题", content="正文")
        self.assertEqual(payload["msg_type"], "text")
        self.assertEqual(payload["content"]["text"], "标题\n\n正文")

    def test_generic_envelope(self) -> None:
        payload = build_webhook_payload("generic", title="标题", content="正文")
        self.assertEqual(
            payload,
            {"title": "标题", "text": "正文", "source": "aigcnews.cn"},
        )


class ChunkTests(unittest.TestCase):
    def test_short_text_stays_single_chunk(self) -> None:
        self.assertEqual(chunk_markdown_for_provider("wecom", "短内容"), ["短内容"])

    def test_paragraph_packing_respects_byte_budget(self) -> None:
        paragraphs = [f"段落{i}-" + "字" * 260 for i in range(10)]
        text = "\n\n".join(paragraphs)
        chunks = chunk_markdown_for_provider("wecom", text)
        self.assertGreater(len(chunks), 1)
        for chunk in chunks:
            self.assertLessEqual(len(chunk.encode("utf-8")), 3500)
        reassembled = "\n\n".join(chunks)
        for marker in [f"段落{i}" for i in range(10)]:
            self.assertIn(marker, reassembled)

    def test_oversized_paragraph_hard_splits_on_char_boundary(self) -> None:
        text = "汉" * 6000  # 18000 字节，无段落边界；恰好在块数上限内
        chunks = chunk_markdown_for_provider("wecom", text)
        for chunk in chunks:
            self.assertLessEqual(len(chunk.encode("utf-8")), 3500)
        self.assertEqual("".join(chunks), text)
        self.assertNotIn("已截断", chunks[-1])

    def test_max_chunks_caps_with_overflow_footer(self) -> None:
        paragraphs = [f"段{i}-" + "字" * 260 for i in range(40)]
        chunks = chunk_markdown_for_provider("wecom", "\n\n".join(paragraphs))
        self.assertEqual(len(chunks), MAX_CHUNKS)
        self.assertIn("完整报告见 https://aigcnews.cn", chunks[-1])
        self.assertLessEqual(len(chunks[-1].encode("utf-8")), 3500)


class WebhookSenderTests(unittest.IsolatedAsyncioTestCase):
    def _sender(self, handler) -> tuple[WebhookSender, list[httpx.Request]]:
        requests: list[httpx.Request] = []

        def _record(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return handler(request)

        return (
            WebhookSender(transport=httpx.MockTransport(_record)),
            requests,
        )

    async def test_send_success_single_chunk(self) -> None:
        sender, requests = self._sender(
            lambda request: httpx.Response(200, json={"errcode": 0, "errmsg": "ok"})
        )
        with patch(
            "backend.app.services.push.webhook_service.socket.getaddrinfo",
            side_effect=_public_getaddrinfo,
        ):
            await sender.send(url=_WECOM_URL, title="测试标题", content="测试内容")
        self.assertEqual(len(requests), 1)
        body = json.loads(requests[0].content)
        self.assertEqual(body["msgtype"], "markdown")
        self.assertIn("测试标题", body["markdown"]["content"])
        self.assertIn("测试内容", body["markdown"]["content"])

    async def test_long_content_sends_multiple_chunks_in_order(self) -> None:
        sender, requests = self._sender(
            lambda request: httpx.Response(200, json={"errcode": 0})
        )
        paragraphs = [f"段落{i}-" + "字" * 260 for i in range(10)]
        with patch(
            "backend.app.services.push.webhook_service.socket.getaddrinfo",
            side_effect=_public_getaddrinfo,
        ):
            await sender.send(url=_WECOM_URL, title="标题", content="\n\n".join(paragraphs))
        self.assertGreater(len(requests), 1)
        joined = "".join(
            json.loads(request.content)["markdown"]["content"] for request in requests
        )
        for marker in [f"段落{i}" for i in range(10)]:
            self.assertIn(marker, joined)

    async def test_http_error_raises_delivery_error(self) -> None:
        sender, _ = self._sender(
            lambda request: httpx.Response(500, text="boom")
        )
        with patch(
            "backend.app.services.push.webhook_service.socket.getaddrinfo",
            side_effect=_public_getaddrinfo,
        ):
            with self.assertRaises(WebhookDeliveryError):
                await sender.send(url=_WECOM_URL, title="t", content="c")

    async def test_platform_errcode_nonzero_raises(self) -> None:
        sender, _ = self._sender(
            lambda request: httpx.Response(
                200, json={"errcode": 81008, "errmsg": "markdown content too long"}
            )
        )
        with patch(
            "backend.app.services.push.webhook_service.socket.getaddrinfo",
            side_effect=_public_getaddrinfo,
        ):
            with self.assertRaises(WebhookDeliveryError):
                await sender.send(url=_WECOM_URL, title="t", content="c")

    async def test_generic_two_xx_without_json_counts_success(self) -> None:
        sender, requests = self._sender(lambda request: httpx.Response(204))
        with patch(
            "backend.app.services.push.webhook_service.socket.getaddrinfo",
            side_effect=_public_getaddrinfo,
        ):
            await sender.send(url=_GENERIC_URL, title="标题", content="内容")
        self.assertEqual(len(requests), 1)
        body = json.loads(requests[0].content)
        self.assertEqual(body["title"], "标题")
        self.assertEqual(body["source"], "aigcnews.cn")

    async def test_ssrf_recheck_blocks_request(self) -> None:
        sender, requests = self._sender(
            lambda request: httpx.Response(200, json={"errcode": 0})
        )
        with patch(
            "backend.app.services.push.webhook_service.socket.getaddrinfo",
            side_effect=_private_getaddrinfo,
        ):
            with self.assertRaises(WebhookUrlError):
                await sender.send(url=_WECOM_URL, title="t", content="c")
        self.assertEqual(requests, [])


class CreateWebhookChannelServiceTests(unittest.IsolatedAsyncioTestCase):
    def _service(self) -> tuple[PushChannelService, FakePushChannelRepository]:
        repo = FakePushChannelRepository()
        return PushChannelService(repo), repo

    async def test_happy_path_probes_then_persists_verified(self) -> None:
        service, repo = self._service()
        sender = FakeWebhookSender()
        with patch(
            "backend.app.services.push.webhook_service.socket.getaddrinfo",
            side_effect=_public_getaddrinfo,
        ):
            channel, created = await service.create_webhook_channel(
                user_id=7,
                url=_WECOM_URL,
                secret_box=_test_box(),
                webhook_sender=sender,
            )
        self.assertTrue(created)
        self.assertTrue(channel["verified"])
        self.assertEqual(channel["channel_type"], "webhook")
        self.assertEqual(channel["target"], _WECOM_URL)
        # 探测即验证：落库前已真实投递一次绑定提示。
        self.assertEqual(len(sender.calls), 1)
        self.assertEqual(sender.calls[0]["url"], _WECOM_URL)
        self.assertIn("绑定成功", sender.calls[0]["content"])
        # 投递凭据以密封配置为准。
        config = unseal_channel_config(_test_box(), channel["encrypted_config"])
        self.assertEqual(config, {"url": _WECOM_URL})
        self.assertEqual(len(repo.rows), 1)

    async def test_duplicate_verified_target_conflicts(self) -> None:
        service, _ = self._service()
        sender = FakeWebhookSender()
        with patch(
            "backend.app.services.push.webhook_service.socket.getaddrinfo",
            side_effect=_public_getaddrinfo,
        ):
            await service.create_webhook_channel(
                user_id=7, url=_WECOM_URL, secret_box=_test_box(), webhook_sender=sender
            )
            with self.assertRaises(PushChannelDuplicateError):
                await service.create_webhook_channel(
                    user_id=7,
                    url=_WECOM_URL,
                    secret_box=_test_box(),
                    webhook_sender=sender,
                )

    async def test_probe_failure_leaves_no_row(self) -> None:
        service, repo = self._service()
        with patch(
            "backend.app.services.push.webhook_service.socket.getaddrinfo",
            side_effect=_public_getaddrinfo,
        ):
            with self.assertRaises(WebhookProbeFailedError):
                await service.create_webhook_channel(
                    user_id=7,
                    url=_WECOM_URL,
                    secret_box=_test_box(),
                    webhook_sender=FakeWebhookSender(fail=True),
                )
        self.assertEqual(repo.rows, {})

    async def test_missing_encryption_key_refuses_storage(self) -> None:
        service, repo = self._service()
        with patch(
            "backend.app.services.push.webhook_service.socket.getaddrinfo",
            side_effect=_public_getaddrinfo,
        ):
            with self.assertRaises(PushChannelSecretError):
                await service.create_webhook_channel(
                    user_id=7,
                    url=_WECOM_URL,
                    secret_box=None,
                    webhook_sender=FakeWebhookSender(),
                )
        self.assertEqual(repo.rows, {})

    async def test_invalid_url_rejected_before_probe(self) -> None:
        service, repo = self._service()
        sender = FakeWebhookSender()
        with self.assertRaises(WebhookUrlError):
            await service.create_webhook_channel(
                user_id=7,
                url="http://insecure.example.com/hook",
                secret_box=_test_box(),
                webhook_sender=sender,
            )
        self.assertEqual(sender.calls, [])
        self.assertEqual(repo.rows, {})


class SendTestMessageServiceTests(unittest.IsolatedAsyncioTestCase):
    async def _webhook_channel(
        self,
        repo: FakePushChannelRepository,
        *,
        url: str = _WECOM_URL,
        **overrides: Any,
    ) -> dict[str, Any]:
        channel = repo.create_channel(
            user_id=7,
            channel_type="webhook",
            target=url,
            encrypted_config=seal_channel_config(_test_box(), {"url": url}),
            verified=True,
        )
        assert channel is not None
        channel.update(overrides)
        repo.rows[channel["id"]].update(overrides)
        return channel

    async def test_webhook_test_message_unseals_and_sends(self) -> None:
        repo = FakePushChannelRepository()
        service = PushChannelService(repo)
        channel = await self._webhook_channel(repo)
        sender = FakeWebhookSender()
        with patch(
            "backend.app.services.push.webhook_service.socket.getaddrinfo",
            side_effect=_public_getaddrinfo,
        ):
            result = await service.send_test_message(
                user_id=7,
                channel_id=channel["id"],
                secret_box=_test_box(),
                webhook_sender=sender,
            )
        self.assertEqual(result["id"], channel["id"])
        self.assertEqual(len(sender.calls), 1)
        self.assertIn("测试", sender.calls[0]["title"])

    async def test_webhook_test_message_requires_verified_active(self) -> None:
        repo = FakePushChannelRepository()
        service = PushChannelService(repo)
        unverified = await self._webhook_channel(repo, verified=False)
        with self.assertRaises(PushChannelNotVerifiedError):
            await service.send_test_message(
                user_id=7,
                channel_id=unverified["id"],
                secret_box=_test_box(),
                webhook_sender=FakeWebhookSender(),
            )
        disabled = await self._webhook_channel(repo, url=_GENERIC_URL, status="disabled")
        with self.assertRaises(PushChannelDisabledError):
            await service.send_test_message(
                user_id=7,
                channel_id=disabled["id"],
                secret_box=_test_box(),
                webhook_sender=FakeWebhookSender(),
            )

    async def test_email_channel_routes_to_email_service(self) -> None:
        repo = FakePushChannelRepository()
        service = PushChannelService(repo)
        channel = repo.create_channel(
            user_id=7,
            channel_type="email",
            target="user@example.com",
            encrypted_config=None,
            verified=True,
        )
        assert channel is not None

        class _FakeEmail:
            def __init__(self) -> None:
                self.calls: list[dict[str, Any]] = []

            async def send_briefing(self, to_email, briefing_content, **kwargs) -> None:
                self.calls.append({"to_email": to_email, "content": briefing_content})

        email = _FakeEmail()
        await service.send_test_message(
            user_id=7, channel_id=channel["id"], email_service=email
        )
        self.assertEqual(email.calls[0]["to_email"], "user@example.com")


class _FakeDeliveryRepository:
    def __init__(self) -> None:
        self.rows: dict[tuple[int, str], dict[str, Any]] = {}
        self._next_id = 1

    def get_delivery(self, *, subscription_id: int, item_key: str):
        row = self.rows.get((subscription_id, item_key))
        return dict(row) if row else None

    def create_delivery(self, *, subscription_id: int, item_key: str):
        key = (subscription_id, item_key)
        if key in self.rows:
            return None
        row = {
            "id": self._next_id,
            "subscription_id": subscription_id,
            "item_key": item_key,
            "status": "pending",
            "attempts": 0,
            "last_error": None,
        }
        self._next_id += 1
        self.rows[key] = row
        return dict(row)

    def mark_delivery_sent(self, *, delivery_id: int, attempts: int) -> None:
        for row in self.rows.values():
            if row["id"] == delivery_id and row["status"] == "pending":
                row["status"] = "sent"
                row["attempts"] = attempts

    def record_attempt_failed(
        self, *, delivery_id: int, attempts: int, last_error: str, exhausted: bool
    ) -> None:
        for row in self.rows.values():
            if row["id"] == delivery_id and row["status"] == "pending":
                row["attempts"] = attempts
                row["last_error"] = last_error
                row["status"] = "failed" if exhausted else "pending"


class _FakeBriefingRepository:
    def __init__(self, briefings: dict[str, dict[str, Any]]) -> None:
        self._briefings = briefings

    def get_briefing_by_date(self, date_str: str):
        return self._briefings.get(date_str)


class _FakeSubscriptionRepository:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def list_active_dispatchable(self, *, frequency: str) -> list[dict[str, Any]]:
        return [row for row in self._rows if row["frequency"] == frequency]


def _webhook_subscription(
    subscription_id: int,
    *,
    url: str = _WECOM_URL,
    source: str = "all",
    frequency: str = "daily",
) -> dict[str, Any]:
    return {
        "id": subscription_id,
        "user_id": 7,
        "channel_id": 100 + subscription_id,
        "source": source,
        "frequency": frequency,
        "status": "active",
        "created_at": _NOW,
        "updated_at": _NOW,
        "channel_type": "webhook",
        "target": url,
        "encrypted_config": seal_channel_config(_test_box(), {"url": url}),
    }


class DispatchWebhookTests(unittest.TestCase):
    def _make_service(
        self,
        *,
        subscriptions: list[dict[str, Any]],
        briefings: dict[str, dict[str, Any]],
        sender: FakeWebhookSender,
        secret_box: Any = None,
    ) -> tuple[SubscriptionDispatchService, _FakeDeliveryRepository]:
        deliveries = _FakeDeliveryRepository()
        service = SubscriptionDispatchService(
            subscriptions=_FakeSubscriptionRepository(subscriptions),
            deliveries=deliveries,
            briefings=_FakeBriefingRepository(briefings),
            secret_box=secret_box if secret_box is not None else _test_box(),
            webhook_sender=sender,
        )
        return service, deliveries

    def test_webhook_delivery_happy_path(self) -> None:
        sender = FakeWebhookSender()
        service, deliveries = self._make_service(
            subscriptions=[_webhook_subscription(1)],
            briefings={"2026-08-05_daily": {"content_zh": "今日 AI 要闻"}},
            sender=sender,
        )
        summary = asyncio.run(service.dispatch_all(today=date(2026, 8, 5)))

        self.assertEqual(summary["sent"], 1)
        self.assertEqual(len(sender.calls), 1)
        self.assertEqual(sender.calls[0]["url"], _WECOM_URL)
        self.assertIn("日报", sender.calls[0]["title"])
        self.assertIn("2026-08-05", sender.calls[0]["title"])
        self.assertEqual(sender.calls[0]["content"], "今日 AI 要闻")
        row = deliveries.rows[(1, "2026-08-05_daily")]
        self.assertEqual(row["status"], "sent")
        self.assertEqual(row["attempts"], 1)

    def test_missing_encryption_key_counts_failed_attempt(self) -> None:
        sender = FakeWebhookSender()
        deliveries = _FakeDeliveryRepository()
        service = SubscriptionDispatchService(
            subscriptions=_FakeSubscriptionRepository([_webhook_subscription(1)]),
            deliveries=deliveries,
            briefings=_FakeBriefingRepository(
                {"2026-08-05_daily": {"content_zh": "今日 AI 要闻"}}
            ),
            secret_box=None,
            webhook_sender=sender,
        )
        summary = asyncio.run(service.dispatch_all(today=date(2026, 8, 5)))

        self.assertEqual(summary["failed"], 1)
        self.assertEqual(sender.calls, [])
        row = deliveries.rows[(1, "2026-08-05_daily")]
        self.assertEqual(row["status"], "pending")
        self.assertEqual(row["attempts"], 1)
        self.assertIn("密钥", row["last_error"])

    def test_sender_failure_records_failed_attempt(self) -> None:
        sender = FakeWebhookSender(fail=True)
        service, deliveries = self._make_service(
            subscriptions=[_webhook_subscription(1)],
            briefings={"2026-08-05_daily": {"content_zh": "今日 AI 要闻"}},
            sender=sender,
        )
        summary = asyncio.run(service.dispatch_all(today=date(2026, 8, 5)))

        self.assertEqual(summary["failed"], 1)
        row = deliveries.rows[(1, "2026-08-05_daily")]
        self.assertEqual(row["attempts"], 1)
        self.assertIn("HTTP 500", row["last_error"])


class CreateChannelSchemaTests(unittest.TestCase):
    def test_webhook_target_accepted(self) -> None:
        request = CreatePushChannelRequest(
            channel_type="webhook", target=f"  {_WECOM_URL}  "
        )
        self.assertEqual(request.target, _WECOM_URL)

    def test_invalid_email_still_422_level_error(self) -> None:
        with self.assertRaises(ValueError):
            CreatePushChannelRequest(channel_type="email", target="not-an-email")

    def test_empty_target_rejected(self) -> None:
        with self.assertRaises(ValueError):
            CreatePushChannelRequest(channel_type="webhook", target="   ")


class WebhookRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.channels = FakePushChannelRepository()
        self.subscriptions = FakeUserSubscriptionRepository(self.channels)
        app = FastAPI()
        app.state.redis = FakeRedis()
        app.include_router(routes_push.router, prefix="/api")

        async def user() -> dict:
            return {"user_id": 7, "email": "owner@example.com", "role": "user"}

        app.dependency_overrides[RequireUser] = user
        app.dependency_overrides[get_push_channel_service] = lambda: (
            PushChannelService(self.channels)
        )
        app.dependency_overrides[get_user_subscription_service] = lambda: (
            UserSubscriptionService(self.subscriptions, self.channels)
        )
        self.sender = FakeWebhookSender()
        self._patchers = [
            patch.object(
                routes_push, "WebhookSender", return_value=self.sender
            ),
            patch.object(
                routes_push,
                "build_push_channel_secret_box",
                side_effect=lambda: _test_box(),
            ),
            patch(
                "backend.app.services.push.webhook_service.socket.getaddrinfo",
                side_effect=_public_getaddrinfo,
            ),
            patch.object(
                routes_push,
                "build_email_service",
                return_value=EmailService(app.state.redis, smtp_host=""),
            ),
        ]
        for patcher in self._patchers:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.client = TestClient(app)

    def test_create_webhook_channel_201_verified(self) -> None:
        response = self.client.post(
            "/api/push/me/channels",
            json={"channel_type": "webhook", "target": _WECOM_URL},
        )
        self.assertEqual(response.status_code, 201, response.text)
        body = response.json()
        self.assertEqual(body["channel_type"], "webhook")
        self.assertTrue(body["verified"])
        self.assertEqual(body["target"], _WECOM_URL)
        self.assertEqual(len(self.sender.calls), 1)

    def test_create_webhook_duplicate_409(self) -> None:
        payload = {"channel_type": "webhook", "target": _WECOM_URL}
        first = self.client.post("/api/push/me/channels", json=payload)
        self.assertEqual(first.status_code, 201, first.text)
        second = self.client.post("/api/push/me/channels", json=payload)
        self.assertEqual(second.status_code, 409, second.text)

    def test_create_webhook_http_url_400(self) -> None:
        response = self.client.post(
            "/api/push/me/channels",
            json={
                "channel_type": "webhook",
                "target": "http://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=k",
            },
        )
        self.assertEqual(response.status_code, 400, response.text)

    def test_create_webhook_probe_failure_400_and_no_row(self) -> None:
        self.sender._fail = True
        response = self.client.post(
            "/api/push/me/channels",
            json={"channel_type": "webhook", "target": _WECOM_URL},
        )
        self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(self.channels.rows, {})

    def test_test_endpoint_delivers_to_webhook_channel(self) -> None:
        created = self.client.post(
            "/api/push/me/channels",
            json={"channel_type": "webhook", "target": _WECOM_URL},
        ).json()
        response = self.client.post(
            f"/api/push/me/channels/{created['id']}/test"
        )
        self.assertEqual(response.status_code, 200, response.text)
        # 一次创建探测 + 一次测试投递
        self.assertEqual(len(self.sender.calls), 2)
        self.assertIn("测试", self.sender.calls[-1]["title"])

    def test_email_channel_flow_unaffected(self) -> None:
        response = self.client.post(
            "/api/push/me/channels", json={"target": "user@example.com"}
        )
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["channel_type"], "email")
        self.assertFalse(response.json()["verified"])


if __name__ == "__main__":
    unittest.main()
