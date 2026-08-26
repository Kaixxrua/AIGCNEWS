"""TelegramConfigAdminService 与 resolve_telegram_config 的契约测试。

钉住的对外语义：
- 投影绝不回明文：secret 只有 *_configured 布尔 + *_masked 脱敏值；
- 更新 secret 留空 = 保留 DB 现值；显式 clear_* = 擦除；
- DB 行整体覆盖 env（无逐字段 env 回落）；
- 保存/重置即失效运行时缓存；
- reader 绑定且读取失败（迁移未应用等）→ Telegram 推送 fail-closed，
  绝不静默回落 env 凭据；
- reader 未绑定（测试/兼容缝）→ 每次请求直读 env，不经缓存；
- 新 bot_token 保存前必过 getMe 校验，username 以 getMe 返回为准；
- setWebhook 的 URL 由 public_base_url 派生，绝不取请求 Host。
"""

from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

import httpx

from backend.app.repositories.telegram_settings_repository import TelegramSettings
from backend.app.services.push.telegram_config_admin import TelegramConfigAdminService
from backend.app.services.push.telegram_config_provider import (
    configure_telegram_settings_reader,
    invalidate_telegram_config_cache,
    reset_telegram_config_provider,
    resolve_telegram_config,
)

ENV_BOT_TOKEN = "env-bot-token-0001"
DB_BOT_TOKEN = "db-bot-token-0002"
NEW_BOT_TOKEN = "110000:new-bot-token-0003"
DB_WEBHOOK_SECRET = "db-webhook-secret-0004"


def _env(**overrides):
    values = {
        "telegram_push_enabled": True,
        "telegram_bot_token": ENV_BOT_TOKEN,
        "telegram_bot_username": "env_bot",
        "telegram_webhook_secret": "env-webhook-secret",
        "telegram_link_ttl_seconds": 300,
        "telegram_request_timeout_seconds": 5.0,
        "public_base_url": "https://env.example.test",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _row(**overrides) -> TelegramSettings:
    values = {
        "enabled": True,
        "bot_token": DB_BOT_TOKEN,
        "bot_username": "db_bot",
        "webhook_secret": DB_WEBHOOK_SECRET,
        "link_ttl_seconds": 600,
        "request_timeout_seconds": 8.0,
        "updated_at": datetime(2026, 8, 25, 10, 0, tzinfo=timezone.utc),
    }
    values.update(overrides)
    return TelegramSettings(**values)


class FakeTelegramSettingsRepository:
    def __init__(self, row: TelegramSettings | None = None) -> None:
        self._row = row
        self.upsert_calls: list[dict] = []
        self.delete_calls = 0

    def get_telegram_settings(self) -> TelegramSettings | None:
        return self._row

    def upsert_telegram_settings(self, **kwargs) -> TelegramSettings:
        self.upsert_calls.append(kwargs)
        self._row = TelegramSettings(
            **kwargs,
            updated_at=datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc),
        )
        return self._row

    def delete_telegram_settings(self) -> int:
        self.delete_calls += 1
        had_row = self._row is not None
        self._row = None
        return 1 if had_row else 0


def _telegram_api_transport(
    *,
    getme_ok: bool = True,
    username: str = "aigc_news_bot",
    webhook_url: str = "",
) -> tuple[httpx.MockTransport, list[httpx.Request]]:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        path = request.url.path
        if path.endswith("/getMe"):
            if not getme_ok:
                return httpx.Response(401, json={"ok": False})
            return httpx.Response(
                200,
                json={"ok": True, "result": {"id": 110000, "username": username}},
            )
        if path.endswith("/getWebhookInfo"):
            return httpx.Response(
                200,
                json={
                    "ok": True,
                    "result": {
                        "url": webhook_url,
                        "pending_update_count": 3,
                        **({"last_error_message": "Connection refused"} if webhook_url else {}),
                    },
                },
            )
        if path.endswith("/setWebhook"):
            return httpx.Response(200, json={"ok": True, "result": True})
        return httpx.Response(404, json={"ok": False})

    return httpx.MockTransport(handler), calls


def _service(
    repo: FakeTelegramSettingsRepository,
    *,
    env=None,
    transport: httpx.MockTransport,
) -> TelegramConfigAdminService:
    return TelegramConfigAdminService(
        repo,
        env_config=env or _env(),
        transport=transport,
    )


class TelegramConfigAdminTests(unittest.IsolatedAsyncioTestCase):
    def tearDown(self) -> None:
        reset_telegram_config_provider()

    async def test_projection_masks_secrets_and_never_exposes_plaintext(self) -> None:
        transport, _calls = _telegram_api_transport()
        repo = FakeTelegramSettingsRepository(_row())
        configure_telegram_settings_reader(repo)
        service = _service(repo, transport=transport)

        projection = await service.get_config()

        self.assertEqual(projection.source, "database")
        self.assertTrue(projection.enabled)
        self.assertEqual(projection.bot_username, "db_bot")
        self.assertEqual(projection.link_ttl_seconds, 600)
        self.assertTrue(projection.bot_token_configured)
        self.assertEqual(projection.bot_token_masked, "db-b****0002")
        self.assertTrue(projection.webhook_secret_configured)
        fields = projection.__dataclass_fields__
        rendered = str({name: getattr(projection, name) for name in fields})
        self.assertNotIn(DB_BOT_TOKEN, rendered)
        self.assertNotIn(DB_WEBHOOK_SECRET, rendered)
        self.assertNotIn(ENV_BOT_TOKEN, rendered)
        # 投影 schema 里不存在任何明文密钥键
        self.assertFalse(any(key in fields for key in ("bot_token", "webhook_secret")))

    async def test_get_config_includes_webhook_status(self) -> None:
        transport, calls = _telegram_api_transport(
            webhook_url="https://env.example.test/api/push/providers/telegram/webhook"
        )
        repo = FakeTelegramSettingsRepository(_row())
        configure_telegram_settings_reader(repo)
        service = _service(repo, transport=transport)

        projection = await service.get_config()

        self.assertIsNotNone(projection.webhook)
        assert projection.webhook is not None
        self.assertEqual(projection.webhook.pending_update_count, 3)
        self.assertEqual(projection.webhook.last_error_message, "Connection refused")
        self.assertTrue(any(c.url.path.endswith("/getWebhookInfo") for c in calls))

    async def test_blank_db_secret_stays_blank_no_env_fallback(self) -> None:
        # DB 行存在即整体覆盖 env：空密文列不回落 env
        transport, _calls = _telegram_api_transport()
        repo = FakeTelegramSettingsRepository(_row(bot_token="", webhook_secret=""))
        configure_telegram_settings_reader(repo)
        service = _service(repo, transport=transport)

        projection = await service.get_config()

        self.assertEqual(projection.source, "database")
        self.assertFalse(projection.bot_token_configured)
        self.assertIsNone(projection.bot_token_masked)
        self.assertFalse(projection.webhook_secret_configured)
        # 无 token → webhook 状态块缺省
        self.assertIsNone(projection.webhook)

    async def test_unconfigured_without_row_falls_back_to_env(self) -> None:
        transport, _calls = _telegram_api_transport()
        repo = FakeTelegramSettingsRepository()
        configure_telegram_settings_reader(repo)
        service = _service(repo, transport=transport)

        projection = await service.get_config()

        self.assertEqual(projection.source, "environment")
        self.assertEqual(projection.bot_username, "env_bot")
        self.assertTrue(projection.bot_token_configured)
        self.assertEqual(projection.bot_token_masked, "env-****0001")
        self.assertIsNone(projection.updated_at)

    async def test_update_retains_existing_secret_when_submitted_blank(self) -> None:
        transport, calls = _telegram_api_transport()
        repo = FakeTelegramSettingsRepository(_row())
        service = _service(repo, transport=transport)

        await service.update_config({"enabled": True, "link_ttl_seconds": 300})

        saved = repo.upsert_calls[-1]
        self.assertEqual(saved["bot_token"], DB_BOT_TOKEN)
        self.assertEqual(saved["webhook_secret"], DB_WEBHOOK_SECRET)
        # 未提交新 token 且已有 username → 不调 getMe
        self.assertFalse(any(c.url.path.endswith("/getMe") for c in calls))

    async def test_update_clear_flag_wipes_secret(self) -> None:
        transport, _calls = _telegram_api_transport()
        repo = FakeTelegramSettingsRepository(_row())
        service = _service(repo, transport=transport)

        projection = await service.update_config(
            {"enabled": False, "clear_webhook_secret": True}
        )

        saved = repo.upsert_calls[-1]
        self.assertEqual(saved["webhook_secret"], "")
        self.assertFalse(projection.webhook_secret_configured)
        self.assertIsNone(projection.webhook_secret_masked)

    async def test_update_new_token_requires_getme_and_backfills_username(self) -> None:
        transport, calls = _telegram_api_transport(username="fresh_bot")
        repo = FakeTelegramSettingsRepository(_row())
        service = _service(repo, transport=transport)

        projection = await service.update_config({"bot_token": NEW_BOT_TOKEN})

        getme = [c for c in calls if c.url.path.endswith("/getMe")]
        self.assertEqual(len(getme), 1)
        self.assertIn(NEW_BOT_TOKEN, getme[0].url.path)
        saved = repo.upsert_calls[-1]
        self.assertEqual(saved["bot_token"], NEW_BOT_TOKEN)
        # username 以 getMe 返回为准，覆盖手工值与 DB 现值
        self.assertEqual(saved["bot_username"], "fresh_bot")
        self.assertEqual(projection.bot_token_masked, "1100****0003")
        rendered = str(
            {name: getattr(projection, name) for name in projection.__dataclass_fields__}
        )
        self.assertNotIn(NEW_BOT_TOKEN, rendered)

    async def test_update_new_token_getme_failure_rejects_save(self) -> None:
        transport, _calls = _telegram_api_transport(getme_ok=False)
        repo = FakeTelegramSettingsRepository(_row())
        service = _service(repo, transport=transport)

        with self.assertRaises(ValueError):
            await service.update_config({"bot_token": NEW_BOT_TOKEN})
        self.assertEqual(repo.upsert_calls, [])

    async def test_update_enable_without_username_backfills_via_getme(self) -> None:
        transport, calls = _telegram_api_transport(username="backfill_bot")
        repo = FakeTelegramSettingsRepository(
            _row(enabled=False, bot_username="", webhook_secret="")
        )
        service = _service(repo, transport=transport)

        await service.update_config({"enabled": True})

        self.assertTrue(any(c.url.path.endswith("/getMe") for c in calls))
        self.assertEqual(repo.upsert_calls[-1]["bot_username"], "backfill_bot")

    async def test_update_validates_ranges(self) -> None:
        transport, _calls = _telegram_api_transport()
        repo = FakeTelegramSettingsRepository()
        service = _service(repo, transport=transport)

        with self.assertRaises(ValueError):
            await service.update_config({"link_ttl_seconds": 59})
        with self.assertRaises(ValueError):
            await service.update_config({"link_ttl_seconds": 3601})
        with self.assertRaises(ValueError):
            await service.update_config({"request_timeout_seconds": 0.5})
        with self.assertRaises(ValueError):
            await service.update_config({"request_timeout_seconds": 31})
        self.assertEqual(repo.upsert_calls, [])

    async def test_update_rejects_changeme_placeholders(self) -> None:
        transport, _calls = _telegram_api_transport()
        repo = FakeTelegramSettingsRepository()
        service = _service(repo, transport=transport)

        with self.assertRaises(ValueError):
            await service.update_config({"bot_token": "CHANGEME-token"})
        with self.assertRaises(ValueError):
            await service.update_config({"webhook_secret": "changeme-secret"})
        self.assertEqual(repo.upsert_calls, [])

    async def test_update_invalidates_runtime_cache(self) -> None:
        transport, _calls = _telegram_api_transport()
        repo = FakeTelegramSettingsRepository(_row(link_ttl_seconds=300))
        configure_telegram_settings_reader(repo)
        self.assertEqual(resolve_telegram_config(env=_env()).link_ttl_seconds, 300)

        service = _service(repo, transport=transport)
        await service.update_config({"link_ttl_seconds": 900})

        # 保存即失效：下一次 resolve 立刻读到新行，不等 60s TTL
        self.assertEqual(resolve_telegram_config(env=_env()).link_ttl_seconds, 900)

    async def test_reset_deletes_row_and_falls_back_to_env(self) -> None:
        transport, _calls = _telegram_api_transport()
        repo = FakeTelegramSettingsRepository(_row())
        configure_telegram_settings_reader(repo)
        service = _service(repo, transport=transport)

        projection = await service.reset_config()

        self.assertEqual(repo.delete_calls, 1)
        self.assertEqual(projection.source, "environment")
        self.assertEqual(projection.bot_username, "env_bot")
        self.assertEqual(projection.link_ttl_seconds, 300)

    async def test_register_webhook_calls_setwebhook_with_derived_url(self) -> None:
        transport, calls = _telegram_api_transport()
        repo = FakeTelegramSettingsRepository(_row())
        configure_telegram_settings_reader(repo)
        service = _service(repo, transport=transport)

        projection = await service.register_webhook()

        callset = [c for c in calls if c.url.path.endswith("/setWebhook")]
        self.assertEqual(len(calls), len([c for c in calls]))
        self.assertEqual(len(callset), 1)
        payload = json.loads(callset[0].content.decode("utf-8"))
        self.assertEqual(
            payload["url"],
            "https://env.example.test/api/push/providers/telegram/webhook",
        )
        self.assertEqual(payload["secret_token"], DB_WEBHOOK_SECRET)
        self.assertIsNotNone(projection.webhook)

    async def test_register_webhook_requires_secret_and_base_url(self) -> None:
        transport, _calls = _telegram_api_transport()
        repo = FakeTelegramSettingsRepository(_row(webhook_secret=""))
        configure_telegram_settings_reader(repo)

        service = _service(repo, transport=transport)
        with self.assertRaises(ValueError):
            await service.register_webhook()

        repo2 = FakeTelegramSettingsRepository(_row())
        configure_telegram_settings_reader(repo2)
        service2 = _service(
            repo2, env=_env(public_base_url=""), transport=transport
        )
        with self.assertRaises(ValueError):
            await service2.register_webhook()

        repo3 = FakeTelegramSettingsRepository(_row(enabled=False))
        configure_telegram_settings_reader(repo3)
        service3 = _service(repo3, transport=transport)
        with self.assertRaises(ValueError):
            await service3.register_webhook()


class TelegramRuntimeConfigResolutionTests(unittest.TestCase):
    """resolve_telegram_config：DB 覆盖 env、reader 故障 fail-closed、缓存只在绑定时生效。"""

    def tearDown(self) -> None:
        reset_telegram_config_provider()

    def test_db_row_overrides_env_wholesale(self) -> None:
        repo = FakeTelegramSettingsRepository(_row())
        configure_telegram_settings_reader(repo)

        config = resolve_telegram_config(env=_env())

        self.assertEqual(config.source, "database")
        self.assertTrue(config.enabled)
        self.assertEqual(config.bot_token, DB_BOT_TOKEN)
        self.assertEqual(config.bot_username, "db_bot")
        self.assertEqual(config.link_ttl_seconds, 600)
        self.assertEqual(config.request_timeout_seconds, 8.0)

    def test_no_row_falls_back_to_environment(self) -> None:
        configure_telegram_settings_reader(FakeTelegramSettingsRepository())

        config = resolve_telegram_config(env=_env())

        self.assertEqual(config.source, "environment")
        self.assertEqual(config.bot_token, ENV_BOT_TOKEN)
        self.assertTrue(config.configured)

    def test_reader_failure_fails_closed_never_env(self) -> None:
        """迁移未应用/DB 故障时绝不静默启用 env 里的 Telegram 凭据。"""

        class BrokenReader:
            def get_telegram_settings(self) -> TelegramSettings | None:
                raise RuntimeError("relation telegram_settings does not exist")

        configure_telegram_settings_reader(BrokenReader())

        config = resolve_telegram_config(env=_env())

        self.assertEqual(config.source, "unconfigured")
        self.assertFalse(config.enabled)
        self.assertFalse(config.configured)
        self.assertEqual(config.bot_token, "")
        self.assertEqual(config.webhook_secret, "")

    def test_reader_failure_is_cached_but_recoverable_after_invalidate(self) -> None:
        class FlakyReader:
            def __init__(self) -> None:
                self.fail = True

            def get_telegram_settings(self) -> TelegramSettings | None:
                if self.fail:
                    raise RuntimeError("db down")
                return _row()

        reader = FlakyReader()
        configure_telegram_settings_reader(reader)
        self.assertEqual(resolve_telegram_config(env=_env()).source, "unconfigured")

        reader.fail = False
        invalidate_telegram_config_cache()
        config = resolve_telegram_config(env=_env())
        self.assertEqual(config.source, "database")

    def test_unbound_reader_reads_env_per_request_without_cache(self) -> None:
        env = _env()
        self.assertEqual(resolve_telegram_config(env=env).bot_username, "env_bot")

        # 无 reader 时不走缓存：env 变更立即可见（测试缝语义）
        env.telegram_push_enabled = False
        self.assertFalse(resolve_telegram_config(env=env).enabled)

    def test_cache_holds_within_ttl_and_invalidate_forces_reload(self) -> None:
        repo = FakeTelegramSettingsRepository(_row(bot_username="first_bot"))
        configure_telegram_settings_reader(repo)
        self.assertEqual(resolve_telegram_config(env=_env()).bot_username, "first_bot")

        # 缓存窗口内直接改行不可见
        repo._row = _row(bot_username="second_bot")
        self.assertEqual(resolve_telegram_config(env=_env()).bot_username, "first_bot")

        invalidate_telegram_config_cache()
        self.assertEqual(resolve_telegram_config(env=_env()).bot_username, "second_bot")


if __name__ == "__main__":
    unittest.main()
