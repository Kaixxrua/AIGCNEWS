"""订阅推送（渠道 + 订阅）契约测试。"""

from __future__ import annotations

import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api import routes_push
from backend.app.api.dependencies import (
    get_briefing_subscription_repository,
    get_push_channel_service,
    get_user_subscription_repository,
    get_user_subscription_service,
)
from backend.app.core.auth import RequireUser
from backend.app.core.config import Settings
from backend.app.domain.wechat_secret_box import WeChatSecretBox
from backend.app.repositories.postgres_user_subscription_repository import (
    SubscriptionChannelMissingError,
)
from backend.app.services import email_service
from backend.app.services.email.otp_store import otp_keys
from backend.app.services.email_service import (
    EmailService,
    OtpSendRateLimitedError,
)
from backend.app.services.push.channel_service import (
    CHANNEL_OTP_PURPOSE,
    PushChannelService,
)
from backend.app.services.push.secrets import (
    PushChannelSecretError,
    build_push_channel_secret_box,
    seal_channel_config,
    unseal_channel_config,
)
from backend.app.services.push.subscription_service import UserSubscriptionService
from backend.tests.test_email_service_contracts import FakeRedis

_NOW = datetime(2026, 8, 6, tzinfo=timezone.utc)


class FakePushChannelRepository:
    def __init__(self) -> None:
        self.rows: dict[int, dict] = {}
        self.next_id = 1

    def create_channel(
        self, *, user_id, channel_type, target, encrypted_config, verified=False
    ) -> dict | None:
        for row in self.rows.values():
            if (
                row["user_id"] == user_id
                and row["channel_type"] == channel_type
                and row["target"] == target
            ):
                return None
        row = {
            "id": self.next_id,
            "user_id": user_id,
            "channel_type": channel_type,
            "target": target,
            "encrypted_config": encrypted_config,
            "verified": verified,
            "status": "active",
            "created_at": _NOW,
            "updated_at": _NOW,
        }
        self.rows[self.next_id] = row
        self.next_id += 1
        return dict(row)

    def find_channel_by_target(self, *, user_id, channel_type, target) -> dict | None:
        for row in self.rows.values():
            if (
                row["user_id"] == user_id
                and row["channel_type"] == channel_type
                and row["target"] == target
            ):
                return dict(row)
        return None

    def get_channel(self, *, user_id, channel_id) -> dict | None:
        row = self.rows.get(channel_id)
        if row is None or row["user_id"] != user_id:
            return None
        return dict(row)

    def list_channels(self, user_id) -> list[dict]:
        return [
            dict(row) for row in self.rows.values() if row["user_id"] == user_id
        ]

    def mark_channel_verified(self, *, user_id, channel_id) -> bool:
        row = self.rows.get(channel_id)
        if row is None or row["user_id"] != user_id:
            return False
        row["verified"] = True
        return True

    def set_channel_status(self, *, user_id, channel_id, status) -> bool:
        row = self.rows.get(channel_id)
        if row is None or row["user_id"] != user_id:
            return False
        row["status"] = status
        return True

    def delete_channel(self, *, user_id, channel_id) -> bool:
        row = self.rows.get(channel_id)
        if row is None or row["user_id"] != user_id:
            return False
        del self.rows[channel_id]
        return True

    def seed_verified_email(self, *, user_id: int, target: str) -> dict:
        row = self.create_channel(
            user_id=user_id,
            channel_type="email",
            target=target,
            encrypted_config=None,
        )
        assert row is not None
        self.mark_channel_verified(user_id=user_id, channel_id=row["id"])
        row["verified"] = True
        return row


class FakeUserSubscriptionRepository:
    def __init__(self, channels: FakePushChannelRepository) -> None:
        self._channels = channels
        self.rows: dict[int, dict] = {}
        self.next_id = 1

    def create_subscription(
        self, *, user_id, channel_id, source, frequency
    ) -> dict | None:
        if channel_id not in self._channels.rows:
            raise SubscriptionChannelMissingError(f"push channel {channel_id} missing")
        for row in self.rows.values():
            if (
                row["user_id"] == user_id
                and row["channel_id"] == channel_id
                and row["source"] == source
                and row["frequency"] == frequency
            ):
                return None
        row = {
            "id": self.next_id,
            "user_id": user_id,
            "channel_id": channel_id,
            "source": source,
            "frequency": frequency,
            "status": "active",
            "created_at": _NOW,
            "updated_at": _NOW,
        }
        self.rows[self.next_id] = row
        self.next_id += 1
        return dict(row)

    def list_subscriptions(self, user_id) -> list[dict]:
        result = []
        for row in self.rows.values():
            if row["user_id"] != user_id:
                continue
            channel = self._channels.rows[row["channel_id"]]
            result.append(
                {**row, "channel_type": channel["channel_type"], "target": channel["target"]}
            )
        return result

    def set_subscription_status(self, *, user_id, subscription_id, status) -> bool:
        row = self.rows.get(subscription_id)
        if row is None or row["user_id"] != user_id:
            return False
        row["status"] = status
        return True

    def delete_subscription(self, *, user_id, subscription_id) -> bool:
        row = self.rows.get(subscription_id)
        if row is None or row["user_id"] != user_id:
            return False
        del self.rows[subscription_id]
        return True


class FakeBriefingSubscriptionRepository:
    """体系 A（briefing_subscriptions）内存仓储：只建模活跃日报读接口。"""

    def __init__(self) -> None:
        self.rows: list[dict] = []

    def add_active(self, *, user_id: int, source: str) -> None:
        self.rows.append({"user_id": user_id, "source": source, "is_active": True})

    def get_user_briefing_subscriptions(self, user_id: int) -> list[dict]:
        return [
            dict(row)
            for row in self.rows
            if row["user_id"] == user_id and row["is_active"]
        ]


class PushChannelSecretTests(unittest.TestCase):
    def test_seal_unseal_roundtrip(self) -> None:
        box = WeChatSecretBox.generate_for_test()
        config = {"webhook_url": "https://example.test/hook", "secret": "s3cr3t"}
        sealed = seal_channel_config(box, config)
        self.assertIsInstance(sealed, str)
        self.assertNotIn("s3cr3t", sealed)
        self.assertEqual(unseal_channel_config(box, sealed), config)

    def test_unseal_with_wrong_key_fails(self) -> None:
        box = WeChatSecretBox.generate_for_test()
        other = WeChatSecretBox.generate_for_test()
        sealed = seal_channel_config(box, {"secret": "s3cr3t"})
        with self.assertRaises(PushChannelSecretError):
            unseal_channel_config(other, sealed)

    def test_seal_without_box_refuses_plaintext_fallback(self) -> None:
        with self.assertRaises(PushChannelSecretError):
            seal_channel_config(None, {"secret": "s3cr3t"})
        with self.assertRaises(PushChannelSecretError):
            unseal_channel_config(None, "{}")

    def test_build_returns_none_when_key_missing(self) -> None:
        config = SimpleNamespace(
            push_channel_encryption_key="",
            push_channel_encryption_key_version="v1",
        )
        self.assertIsNone(build_push_channel_secret_box(config=config))

    def test_build_returns_none_when_key_invalid(self) -> None:
        config = SimpleNamespace(
            push_channel_encryption_key="!!!not-base64!!!",
            push_channel_encryption_key_version="v1",
        )
        with self.assertLogs("backend.app.services.push.secrets", level="WARNING"):
            self.assertIsNone(build_push_channel_secret_box(config=config))

    def test_build_with_valid_key(self) -> None:
        config = SimpleNamespace(
            push_channel_encryption_key=WeChatSecretBox.generate_key_material(),
            push_channel_encryption_key_version="v2",
        )
        box = build_push_channel_secret_box(config=config)
        self.assertIsNotNone(box)
        self.assertEqual(box.key_version, "v2")

    def test_settings_reject_placeholder_key(self) -> None:
        with self.assertRaises(ValueError):
            Settings(push_channel_encryption_key="CHANGEME-example")


class PushChannelOtpStoreTests(unittest.TestCase):
    def test_otp_keys_use_dedicated_prefixes(self) -> None:
        code_key, lock_key, attempts_key = otp_keys(
            "User@Example.com", "push_channel_verify"
        )
        self.assertEqual(code_key, "email:push:code:user@example.com")
        self.assertEqual(lock_key, "email:push:lock:user@example.com")
        self.assertEqual(attempts_key, "email:push:attempts:user@example.com")


class PushChannelOtpFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_send_and_verify_otp(self) -> None:
        redis = FakeRedis()
        service = EmailService(redis, smtp_host="")
        # SMTP 未配置的投递成功路径仅在开发环境成立（OTP 明文日志限定 dev）
        with (
            patch(
                "backend.app.services.email_service._gen_otp", return_value="123456"
            ),
            patch.object(email_service.settings, "env", "development"),
        ):
            await service.send_otp("user@example.com", purpose=CHANNEL_OTP_PURPOSE)
        self.assertEqual(
            redis.values["email:push:code:user@example.com"], "123456"
        )
        ok = await service.verify_otp(
            "user@example.com", "123456", purpose=CHANNEL_OTP_PURPOSE
        )
        self.assertTrue(ok)
        self.assertNotIn("email:push:code:user@example.com", redis.values)

    async def test_send_otp_hits_cooldown(self) -> None:
        redis = FakeRedis()
        service = EmailService(redis, smtp_host="")
        with patch.object(email_service.settings, "env", "development"):
            await service.send_otp("user@example.com", purpose=CHANNEL_OTP_PURPOSE)
        # 冷却命中先于投递判定，第二针在任意环境下都抛 429 领域错误
        with self.assertRaises(OtpSendRateLimitedError):
            await service.send_otp("user@example.com", purpose=CHANNEL_OTP_PURPOSE)


class _PushRouteTestBase(unittest.TestCase):
    def setUp(self) -> None:
        self.redis = FakeRedis()
        self.channels = FakePushChannelRepository()
        self.subscriptions = FakeUserSubscriptionRepository(self.channels)
        self.briefing_subscriptions = FakeBriefingSubscriptionRepository()
        app = FastAPI()
        app.state.redis = self.redis
        app.include_router(routes_push.router, prefix="/api")

        async def user() -> dict:
            # 既有 CRUD 用例的语义不受档位配额干扰：fixture 默认会员档
            # （档位校验的免费档行为由 PushSubscriptionQuotaTests 专项覆盖）
            return {
                "user_id": 7,
                "email": "owner@example.com",
                "role": "user",
                "membership_tier": "member",
            }

        app.dependency_overrides[RequireUser] = user
        app.dependency_overrides[get_push_channel_service] = lambda: (
            PushChannelService(self.channels)
        )
        app.dependency_overrides[get_user_subscription_service] = lambda: (
            UserSubscriptionService(self.subscriptions, self.channels)
        )
        # 档位校验跨体系合计所需的两个读仓储（PR3 新增依赖）
        app.dependency_overrides[get_briefing_subscription_repository] = lambda: (
            self.briefing_subscriptions
        )
        app.dependency_overrides[get_user_subscription_repository] = lambda: (
            self.subscriptions
        )
        # 邮件服务固定走 dev 模式（开发环境 + SMTP 未配置），避免测试触网；
        # 非开发环境 SMTP 未配置会拒绝发码（OTP 明文日志限定 dev）
        self.email_service = EmailService(self.redis, smtp_host="")
        self._email_patcher = patch.object(
            routes_push, "build_email_service", return_value=self.email_service
        )
        self._email_patcher.start()
        self.addCleanup(self._email_patcher.stop)
        self._env_patcher = patch.object(email_service.settings, "env", "development")
        self._env_patcher.start()
        self.addCleanup(self._env_patcher.stop)
        self.app = app
        self.client = TestClient(app)

    def _create_channel(self, email: str = "user@example.com") -> dict:
        response = self.client.post(
            "/api/push/me/channels", json={"target": email}
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def _stored_otp(self, email: str) -> str:
        return self.redis.values[f"email:push:code:{email}"]

    def _create_verified_channel(self, email: str = "user@example.com") -> dict:
        channel = self._create_channel(email)
        response = self.client.post(
            f"/api/push/me/channels/{channel['id']}/verify",
            json={"code": self._stored_otp(email)},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()


class PushChannelRouteTests(_PushRouteTestBase):
    def test_create_channel_sends_otp_and_stays_unverified(self) -> None:
        body = self._create_channel("User@Example.com")
        self.assertEqual(body["channel_type"], "email")
        self.assertEqual(body["target"], "user@example.com")
        self.assertFalse(body["verified"])
        self.assertEqual(body["status"], "active")
        self.assertIn("email:push:code:user@example.com", self.redis.values)
        self.assertIn("email:push:lock:user@example.com", self.redis.values)

    def test_create_channel_rejects_invalid_email(self) -> None:
        response = self.client.post(
            "/api/push/me/channels", json={"target": "not-an-email"}
        )
        self.assertEqual(response.status_code, 422)

    def test_create_duplicate_verified_channel_conflicts(self) -> None:
        self._create_verified_channel()
        response = self.client.post(
            "/api/push/me/channels", json={"target": "user@example.com"}
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"], "该邮箱已绑定推送渠道")

    def test_create_duplicate_unverified_channel_resends_otp(self) -> None:
        first = self._create_channel()
        # 跳过 60 秒冷却，模拟用户稍后重新提交。
        self.redis.values.pop("email:push:lock:user@example.com")
        response = self.client.post(
            "/api/push/me/channels", json={"target": "user@example.com"}
        )
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["id"], first["id"])
        self.assertEqual(len(self.channels.rows), 1)

    def test_verify_channel_marks_verified(self) -> None:
        channel = self._create_channel()
        response = self.client.post(
            f"/api/push/me/channels/{channel['id']}/verify",
            json={"code": self._stored_otp("user@example.com")},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["verified"])

    def test_verify_channel_rejects_wrong_code(self) -> None:
        channel = self._create_channel()
        response = self.client.post(
            f"/api/push/me/channels/{channel['id']}/verify",
            json={"code": "000000"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "验证码错误或已过期")

    def test_verify_channel_rejects_malformed_code(self) -> None:
        response = self.client.post(
            "/api/push/me/channels/1/verify", json={"code": "abc"}
        )
        self.assertEqual(response.status_code, 422)

    def test_verify_other_users_channel_returns_404(self) -> None:
        foreign = self.channels.seed_verified_email(
            user_id=8, target="other@example.com"
        )
        response = self.client.post(
            f"/api/push/me/channels/{foreign['id']}/verify",
            json={"code": "123456"},
        )
        self.assertEqual(response.status_code, 404)

    def test_list_channels_scoped_to_user(self) -> None:
        self.channels.seed_verified_email(user_id=8, target="other@example.com")
        self._create_channel()
        response = self.client.get("/api/push/me/channels")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["cache-control"], "no-store")
        items = response.json()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["target"], "user@example.com")

    def test_update_channel_status(self) -> None:
        channel = self._create_verified_channel()
        response = self.client.patch(
            f"/api/push/me/channels/{channel['id']}", json={"status": "disabled"}
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "disabled")
        response = self.client.patch(
            f"/api/push/me/channels/{channel['id']}", json={"status": "bogus"}
        )
        self.assertEqual(response.status_code, 422)

    def test_delete_channel(self) -> None:
        channel = self._create_channel()
        response = self.client.delete(f"/api/push/me/channels/{channel['id']}")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["deleted"])
        response = self.client.delete(f"/api/push/me/channels/{channel['id']}")
        self.assertEqual(response.status_code, 404)

    def test_create_channel_rate_limited_per_ip(self) -> None:
        for index in range(5):
            response = self.client.post(
                "/api/push/me/channels", json={"target": f"user{index}@example.com"}
            )
            self.assertEqual(response.status_code, 201, response.text)
        response = self.client.post(
            "/api/push/me/channels", json={"target": "user5@example.com"}
        )
        self.assertEqual(response.status_code, 429)

    def test_test_email_requires_verified_channel(self) -> None:
        channel = self._create_channel()
        response = self.client.post(f"/api/push/me/channels/{channel['id']}/test")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "推送渠道尚未验证")

    def test_test_email_smtp_unconfigured_returns_503(self) -> None:
        channel = self._create_verified_channel()
        response = self.client.post(f"/api/push/me/channels/{channel['id']}/test")
        self.assertEqual(response.status_code, 503)

    def test_test_email_success_through_smtp_pipeline(self) -> None:
        channel = self._create_verified_channel()
        smtp_service = EmailService(
            self.redis,
            smtp_host="smtp.example.test",
            smtp_port=465,
            smtp_username="u",
            smtp_password="p",
            smtp_from_email="noreply@example.test",
        )
        with (
            patch.object(
                routes_push, "build_email_service", return_value=smtp_service
            ),
            patch("aiosmtplib.send", new_callable=AsyncMock) as mock_send,
        ):
            response = self.client.post(
                f"/api/push/me/channels/{channel['id']}/test"
            )
        self.assertEqual(response.status_code, 200, response.text)
        mock_send.assert_awaited_once()
        message = mock_send.await_args.args[0]
        self.assertEqual(message["To"], "user@example.com")
        self.assertIn("渠道测试", message["Subject"])


class UserSubscriptionRouteTests(_PushRouteTestBase):
    def test_create_subscription_success(self) -> None:
        channel = self._create_verified_channel()
        response = self.client.post(
            "/api/push/me/subscriptions",
            json={"channel_id": channel["id"], "source": "github", "frequency": "daily"},
        )
        self.assertEqual(response.status_code, 201, response.text)
        body = response.json()
        self.assertEqual(body["channel_id"], channel["id"])
        self.assertEqual(body["channel_type"], "email")
        self.assertEqual(body["target"], "user@example.com")
        self.assertEqual(body["source"], "github")
        self.assertEqual(body["frequency"], "daily")
        self.assertEqual(body["status"], "active")

    def test_create_subscription_defaults(self) -> None:
        channel = self._create_verified_channel()
        response = self.client.post(
            "/api/push/me/subscriptions", json={"channel_id": channel["id"]}
        )
        self.assertEqual(response.status_code, 201, response.text)
        body = response.json()
        self.assertEqual(body["source"], "all")
        self.assertEqual(body["frequency"], "daily")

    def test_create_subscription_rejects_invalid_source(self) -> None:
        channel = self._create_verified_channel()
        response = self.client.post(
            "/api/push/me/subscriptions",
            json={"channel_id": channel["id"], "source": "weibo"},
        )
        self.assertEqual(response.status_code, 422)

    def test_create_subscription_requires_verified_channel(self) -> None:
        channel = self._create_channel()
        response = self.client.post(
            "/api/push/me/subscriptions", json={"channel_id": channel["id"]}
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "推送渠道尚未验证")

    def test_create_subscription_rejects_disabled_channel(self) -> None:
        channel = self._create_verified_channel()
        self.client.patch(
            f"/api/push/me/channels/{channel['id']}", json={"status": "disabled"}
        )
        response = self.client.post(
            "/api/push/me/subscriptions", json={"channel_id": channel["id"]}
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "推送渠道已停用")

    def test_create_subscription_unknown_channel_returns_404(self) -> None:
        response = self.client.post(
            "/api/push/me/subscriptions", json={"channel_id": 999}
        )
        self.assertEqual(response.status_code, 404)

    def test_create_subscription_other_users_channel_returns_404(self) -> None:
        foreign = self.channels.seed_verified_email(
            user_id=8, target="other@example.com"
        )
        response = self.client.post(
            "/api/push/me/subscriptions", json={"channel_id": foreign["id"]}
        )
        self.assertEqual(response.status_code, 404)

    def test_create_duplicate_subscription_conflicts(self) -> None:
        channel = self._create_verified_channel()
        payload = {"channel_id": channel["id"], "source": "arxiv", "frequency": "daily"}
        first = self.client.post("/api/push/me/subscriptions", json=payload)
        self.assertEqual(first.status_code, 201, first.text)
        second = self.client.post("/api/push/me/subscriptions", json=payload)
        self.assertEqual(second.status_code, 409)
        self.assertEqual(
            second.json()["detail"], "该渠道下已存在相同来源与频率的订阅"
        )

    def test_list_subscriptions_joined_with_channel(self) -> None:
        channel = self._create_verified_channel()
        self.client.post(
            "/api/push/me/subscriptions",
            json={"channel_id": channel["id"], "source": "arxiv"},
        )
        self.client.post(
            "/api/push/me/subscriptions",
            json={"channel_id": channel["id"], "source": "github"},
        )
        response = self.client.get("/api/push/me/subscriptions")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["cache-control"], "no-store")
        items = response.json()
        self.assertEqual(len(items), 2)
        self.assertEqual({item["source"] for item in items}, {"arxiv", "github"})
        self.assertTrue(all(item["target"] == "user@example.com" for item in items))

    def test_update_subscription_status(self) -> None:
        channel = self._create_verified_channel()
        created = self.client.post(
            "/api/push/me/subscriptions", json={"channel_id": channel["id"]}
        ).json()
        response = self.client.patch(
            f"/api/push/me/subscriptions/{created['id']}", json={"status": "paused"}
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "paused")
        response = self.client.patch(
            "/api/push/me/subscriptions/999", json={"status": "paused"}
        )
        self.assertEqual(response.status_code, 404)

    def test_delete_subscription(self) -> None:
        channel = self._create_verified_channel()
        created = self.client.post(
            "/api/push/me/subscriptions", json={"channel_id": channel["id"]}
        ).json()
        response = self.client.delete(f"/api/push/me/subscriptions/{created['id']}")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["deleted"])
        response = self.client.delete(f"/api/push/me/subscriptions/{created['id']}")
        self.assertEqual(response.status_code, 404)


class PushSubscriptionQuotaTests(_PushRouteTestBase):
    """体系 B 路由级档位契约：免费 1 模块/会员全模块，跨体系合计 + 存量豁免。"""

    def _as_user(self, *, role: str = "user", tier: str = "free") -> None:
        async def user() -> dict:
            return {
                "user_id": 7,
                "email": "owner@example.com",
                "role": role,
                "membership_tier": tier,
            }

        self.app.dependency_overrides[RequireUser] = user

    def test_free_tier_first_subscription_created_second_source_rejected(self) -> None:
        self._as_user()
        channel = self._create_verified_channel()
        first = self.client.post(
            "/api/push/me/subscriptions",
            json={"channel_id": channel["id"], "source": "github"},
        )
        self.assertEqual(first.status_code, 201, first.text)
        second = self.client.post(
            "/api/push/me/subscriptions",
            json={"channel_id": channel["id"], "source": "news"},
        )
        self.assertEqual(second.status_code, 403, second.text)
        self.assertEqual(
            second.json()["detail"],
            "免费档最多订阅 1 个日报模块，开通会员解锁全部 8 个模块",
        )

    def test_free_tier_same_source_on_new_channel_is_not_a_new_module(self) -> None:
        # 存量豁免：已活跃 source 换渠道重复订阅不视为新增模块
        self._as_user()
        first_channel = self._create_verified_channel("a@example.com")
        second_channel = self._create_verified_channel("b@example.com")
        first = self.client.post(
            "/api/push/me/subscriptions",
            json={"channel_id": first_channel["id"], "source": "github"},
        )
        self.assertEqual(first.status_code, 201, first.text)
        second = self.client.post(
            "/api/push/me/subscriptions",
            json={"channel_id": second_channel["id"], "source": "github"},
        )
        self.assertEqual(second.status_code, 201, second.text)

    def test_member_tier_subscribes_multiple_sources(self) -> None:
        # 基类 fixture 默认会员档
        channel = self._create_verified_channel()
        for source in ("github", "news", "x"):
            response = self.client.post(
                "/api/push/me/subscriptions",
                json={"channel_id": channel["id"], "source": source},
            )
            self.assertEqual(response.status_code, 201, response.text)

    def test_admin_bypasses_quota(self) -> None:
        self._as_user(role="admin")
        channel = self._create_verified_channel()
        for source in ("github", "news"):
            response = self.client.post(
                "/api/push/me/subscriptions",
                json={"channel_id": channel["id"], "source": source},
            )
            self.assertEqual(response.status_code, 201, response.text)

    def test_resume_counts_toward_quota_after_downgrade(self) -> None:
        # 会员期建 2 模块 → 全暂停 → 降级免费档 → 恢复第 1 个放行、第 2 个 403
        channel = self._create_verified_channel()
        created = [
            self.client.post(
                "/api/push/me/subscriptions",
                json={"channel_id": channel["id"], "source": source},
            ).json()
            for source in ("github", "news")
        ]
        for item in created:
            paused = self.client.patch(
                f"/api/push/me/subscriptions/{item['id']}", json={"status": "paused"}
            )
            self.assertEqual(paused.status_code, 200, paused.text)

        self._as_user()  # 降级免费档
        resumed = self.client.patch(
            f"/api/push/me/subscriptions/{created[0]['id']}", json={"status": "active"}
        )
        self.assertEqual(resumed.status_code, 200, resumed.text)
        rejected = self.client.patch(
            f"/api/push/me/subscriptions/{created[1]['id']}", json={"status": "active"}
        )
        self.assertEqual(rejected.status_code, 403, rejected.text)
        self.assertEqual(
            rejected.json()["detail"],
            "免费档最多订阅 1 个日报模块，开通会员解锁全部 8 个模块",
        )

    def test_idempotent_patch_on_active_subscription_skips_quota(self) -> None:
        self._as_user()
        channel = self._create_verified_channel()
        created = self.client.post(
            "/api/push/me/subscriptions",
            json={"channel_id": channel["id"], "source": "github"},
        ).json()
        response = self.client.patch(
            f"/api/push/me/subscriptions/{created['id']}", json={"status": "active"}
        )
        self.assertEqual(response.status_code, 200, response.text)

    def test_cross_system_sources_are_counted_together(self) -> None:
        # 体系 A 已活跃 github：免费档在体系 B 订 news 被拒，订 github 去重放行
        self._as_user()
        self.briefing_subscriptions.add_active(user_id=7, source="github")
        channel = self._create_verified_channel()
        rejected = self.client.post(
            "/api/push/me/subscriptions",
            json={"channel_id": channel["id"], "source": "news"},
        )
        self.assertEqual(rejected.status_code, 403, rejected.text)
        deduped = self.client.post(
            "/api/push/me/subscriptions",
            json={"channel_id": channel["id"], "source": "github"},
        )
        self.assertEqual(deduped.status_code, 201, deduped.text)


if __name__ == "__main__":
    unittest.main()
