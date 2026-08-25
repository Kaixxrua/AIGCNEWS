"""OAuthConfigAdminService 与 resolve_oauth_config 的契约测试。

钉住的对外语义：
- 投影绝不回明文：密文只有 *_configured 布尔 + *_masked 脱敏值；
- 更新密文留空 = 保留 DB 现值；显式 clear_* = 擦除；
- DB 行整体覆盖 env 的 provider/TTL/基址（无逐字段 env 回落）；
- 保存/重置即失效运行时缓存；
- reader 绑定且读取失败（迁移未应用等）→ OAuth fail-closed，绝不静默回落 env 凭据；
- reader 未绑定（测试/兼容缝）→ 每次请求直读 env，不经缓存。
"""

from __future__ import annotations

import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

from backend.app.repositories.oauth_settings_repository import OAuthSettings
from backend.app.services.auth.oauth.config_admin import OAuthConfigAdminService
from backend.app.services.auth.oauth.runtime_config import (
    configure_oauth_settings_reader,
    invalidate_oauth_config_cache,
    reset_oauth_config_provider,
    resolve_oauth_config,
)

ENV_GITHUB_SECRET = "env-github-secret-0001"
DB_GITHUB_SECRET = "db-github-secret-0002"


def _env(**overrides):
    values = {
        "oauth_enabled_providers": "github",
        "public_base_url": "https://env.example.test",
        "github_oauth_client_id": "env-github-id",
        "github_oauth_client_secret": ENV_GITHUB_SECRET,
        "google_oauth_client_id": "",
        "google_oauth_client_secret": "",
        "wechat_oauth_app_id": "",
        "wechat_oauth_app_secret": "",
        "oauth_state_ttl_seconds": 300,
        "oauth_handoff_ttl_seconds": 120,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _row(**overrides) -> OAuthSettings:
    values = {
        "enabled_providers": "github,google",
        "public_base_url": "https://db.example.test",
        "github_client_id": "db-github-id",
        "github_client_secret": DB_GITHUB_SECRET,
        "google_client_id": "db-google-id",
        "google_client_secret": "db-google-secret-0123456789",
        "wechat_app_id": "",
        "wechat_app_secret": "",
        "state_ttl_seconds": 600,
        "handoff_ttl_seconds": 90,
        "updated_at": datetime(2026, 8, 25, 10, 0, tzinfo=timezone.utc),
    }
    values.update(overrides)
    return OAuthSettings(**values)


class FakeOAuthSettingsRepository:
    def __init__(self, row: OAuthSettings | None = None) -> None:
        self._row = row
        self.upsert_calls: list[dict] = []
        self.delete_calls = 0

    def get_oauth_settings(self) -> OAuthSettings | None:
        return self._row

    def upsert_oauth_settings(self, **kwargs) -> OAuthSettings:
        self.upsert_calls.append(kwargs)
        self._row = OAuthSettings(
            **kwargs,
            updated_at=datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc),
        )
        return self._row

    def delete_oauth_settings(self) -> int:
        self.delete_calls += 1
        had_row = self._row is not None
        self._row = None
        return 1 if had_row else 0


class OAuthConfigAdminTests(unittest.IsolatedAsyncioTestCase):
    def tearDown(self) -> None:
        reset_oauth_config_provider()

    async def test_projection_masks_secrets_and_never_exposes_plaintext(self) -> None:
        repo = FakeOAuthSettingsRepository(_row())
        configure_oauth_settings_reader(repo)
        service = OAuthConfigAdminService(repo, env_config=_env())

        projection = await service.get_config()

        self.assertEqual(projection.source, "database")
        self.assertEqual(projection.enabled_providers, ["github", "google"])
        self.assertEqual(projection.state_ttl_seconds, 600)
        self.assertTrue(projection.github_client_secret_configured)
        self.assertEqual(projection.github_client_secret_masked, "db-g****0002")
        self.assertTrue(projection.google_client_secret_configured)
        self.assertFalse(projection.wechat_app_secret_configured)
        fields = projection.__dataclass_fields__
        rendered = str({name: getattr(projection, name) for name in fields})
        self.assertNotIn(DB_GITHUB_SECRET, rendered)
        self.assertNotIn(ENV_GITHUB_SECRET, rendered)
        self.assertNotIn("db-google-secret-0123456789", rendered)
        # 投影 schema 里不存在任何明文密钥键
        self.assertFalse(any(key.endswith("_secret") for key in fields))

    async def test_blank_db_secret_stays_blank_no_env_fallback(self) -> None:
        # DB 行存在即整体覆盖 env：空密文列不回落 env
        repo = FakeOAuthSettingsRepository(_row(github_client_secret=""))
        configure_oauth_settings_reader(repo)
        service = OAuthConfigAdminService(repo, env_config=_env())

        projection = await service.get_config()

        self.assertEqual(projection.source, "database")
        self.assertFalse(projection.github_client_secret_configured)
        self.assertIsNone(projection.github_client_secret_masked)

    async def test_unconfigured_without_row_falls_back_to_env(self) -> None:
        repo = FakeOAuthSettingsRepository()
        configure_oauth_settings_reader(repo)
        service = OAuthConfigAdminService(repo, env_config=_env())

        projection = await service.get_config()

        self.assertEqual(projection.source, "environment")
        self.assertEqual(projection.enabled_providers, ["github"])
        self.assertTrue(projection.github_client_secret_configured)
        self.assertEqual(projection.github_client_secret_masked, "env-****0001")
        self.assertIsNone(projection.updated_at)

    async def test_update_retains_existing_secret_when_submitted_blank(self) -> None:
        repo = FakeOAuthSettingsRepository(_row())
        service = OAuthConfigAdminService(repo, env_config=_env())

        await service.update_config({"enabled_providers": ["github"], "state_ttl_seconds": 300})

        saved = repo.upsert_calls[-1]
        self.assertEqual(saved["github_client_secret"], DB_GITHUB_SECRET)
        self.assertEqual(saved["google_client_secret"], "db-google-secret-0123456789")

    async def test_update_clear_flag_wipes_secret(self) -> None:
        repo = FakeOAuthSettingsRepository(_row())
        service = OAuthConfigAdminService(repo, env_config=_env())

        projection = await service.update_config(
            {"enabled_providers": ["github"], "clear_github_client_secret": True}
        )

        saved = repo.upsert_calls[-1]
        self.assertEqual(saved["github_client_secret"], "")
        self.assertFalse(projection.github_client_secret_configured)
        self.assertIsNone(projection.github_client_secret_masked)

    async def test_update_stores_new_secret_and_masks_it(self) -> None:
        repo = FakeOAuthSettingsRepository()
        service = OAuthConfigAdminService(repo, env_config=_env())

        projection = await service.update_config(
            {"github_client_secret": "gho_newsecretvalue1234"}
        )

        saved = repo.upsert_calls[-1]
        self.assertEqual(saved["github_client_secret"], "gho_newsecretvalue1234")
        self.assertEqual(projection.github_client_secret_masked, "gho_****1234")
        rendered = str({name: getattr(projection, name) for name in projection.__dataclass_fields__})
        self.assertNotIn("gho_newsecretvalue1234", rendered)

    async def test_update_validates_ttl_and_base_url(self) -> None:
        repo = FakeOAuthSettingsRepository()
        service = OAuthConfigAdminService(repo, env_config=_env())

        with self.assertRaises(ValueError):
            await service.update_config({"state_ttl_seconds": 59})
        with self.assertRaises(ValueError):
            await service.update_config({"state_ttl_seconds": 901})
        with self.assertRaises(ValueError):
            await service.update_config({"handoff_ttl_seconds": 29})
        with self.assertRaises(ValueError):
            await service.update_config({"handoff_ttl_seconds": 601})
        with self.assertRaises(ValueError):
            await service.update_config({"public_base_url": "not-a-url"})
        with self.assertRaises(ValueError):
            await service.update_config({"public_base_url": "ftp://oauth.example.test"})
        with self.assertRaises(ValueError):
            await service.update_config({"public_base_url": "https://oauth.example.test/?x=1"})
        self.assertEqual(repo.upsert_calls, [])

    async def test_update_rejects_changeme_placeholders(self) -> None:
        repo = FakeOAuthSettingsRepository()
        service = OAuthConfigAdminService(repo, env_config=_env())

        with self.assertRaises(ValueError):
            await service.update_config({"github_client_secret": "CHANGEME-github"})
        with self.assertRaises(ValueError):
            await service.update_config({"wechat_app_secret": "changeme-wechat"})
        self.assertEqual(repo.upsert_calls, [])

    async def test_update_normalizes_base_url_trailing_slash(self) -> None:
        repo = FakeOAuthSettingsRepository()
        service = OAuthConfigAdminService(repo, env_config=_env())

        await service.update_config({"public_base_url": "https://oauth.example.test/"})

        self.assertEqual(repo.upsert_calls[-1]["public_base_url"], "https://oauth.example.test")

    async def test_update_invalidates_runtime_cache(self) -> None:
        repo = FakeOAuthSettingsRepository(_row(enabled_providers="github"))
        configure_oauth_settings_reader(repo)
        self.assertEqual(
            resolve_oauth_config(env=_env()).enabled_providers, ("github",)
        )

        service = OAuthConfigAdminService(repo, env_config=_env())
        await service.update_config({"enabled_providers": ["wechat"]})

        # 保存即失效：下一次 resolve 立刻读到新行，不等 60s TTL
        self.assertEqual(resolve_oauth_config(env=_env()).enabled_providers, ("wechat",))

    async def test_reset_deletes_row_and_falls_back_to_env(self) -> None:
        repo = FakeOAuthSettingsRepository(_row())
        configure_oauth_settings_reader(repo)
        service = OAuthConfigAdminService(repo, env_config=_env())

        projection = await service.reset_config()

        self.assertEqual(repo.delete_calls, 1)
        self.assertEqual(projection.source, "environment")
        self.assertEqual(projection.enabled_providers, ["github"])
        self.assertEqual(projection.state_ttl_seconds, 300)


class OAuthRuntimeConfigResolutionTests(unittest.TestCase):
    """resolve_oauth_config：DB 覆盖 env、reader 故障 fail-closed、缓存只在绑定时生效。"""

    def tearDown(self) -> None:
        reset_oauth_config_provider()

    def test_db_row_overrides_env_wholesale(self) -> None:
        repo = FakeOAuthSettingsRepository(_row())
        configure_oauth_settings_reader(repo)

        config = resolve_oauth_config(env=_env())

        self.assertEqual(config.source, "database")
        self.assertEqual(config.enabled_providers, ("github", "google"))
        self.assertEqual(config.public_base_url, "https://db.example.test")
        self.assertEqual(config.state_ttl_seconds, 600)
        self.assertEqual(config.github_client_secret, DB_GITHUB_SECRET)
        self.assertEqual(config.wechat_app_secret, "")

    def test_no_row_falls_back_to_environment(self) -> None:
        configure_oauth_settings_reader(FakeOAuthSettingsRepository())

        config = resolve_oauth_config(env=_env())

        self.assertEqual(config.source, "environment")
        self.assertEqual(config.enabled_providers, ("github",))
        self.assertEqual(config.github_client_secret, ENV_GITHUB_SECRET)

    def test_reader_failure_fails_closed_never_env(self) -> None:
        """迁移未应用/DB 故障时绝不静默启用 env 里的 OAuth 凭据。"""

        class BrokenReader:
            def get_oauth_settings(self) -> OAuthSettings | None:
                raise RuntimeError("relation oauth_settings does not exist")

        configure_oauth_settings_reader(BrokenReader())

        config = resolve_oauth_config(env=_env())

        self.assertEqual(config.source, "unconfigured")
        self.assertEqual(config.enabled_providers, ())
        self.assertEqual(config.configured_providers, ())
        self.assertEqual(config.github_client_secret, "")

    def test_reader_failure_is_cached_but_recoverable_after_invalidate(self) -> None:
        class FlakyReader:
            def __init__(self) -> None:
                self.fail = True

            def get_oauth_settings(self) -> OAuthSettings | None:
                if self.fail:
                    raise RuntimeError("db down")
                return _row()

        reader = FlakyReader()
        configure_oauth_settings_reader(reader)
        self.assertEqual(resolve_oauth_config(env=_env()).source, "unconfigured")

        reader.fail = False
        invalidate_oauth_config_cache()
        config = resolve_oauth_config(env=_env())
        self.assertEqual(config.source, "database")

    def test_unbound_reader_reads_env_per_request_without_cache(self) -> None:
        env = _env()
        self.assertEqual(resolve_oauth_config(env=env).enabled_providers, ("github",))

        # 无 reader 时不走缓存：env 变更立即可见（测试缝语义）
        env.oauth_enabled_providers = "google"
        self.assertEqual(resolve_oauth_config(env=env).enabled_providers, ("google",))

    def test_cache_holds_within_ttl_and_invalidate_forces_reload(self) -> None:
        repo = FakeOAuthSettingsRepository(_row(enabled_providers="github"))
        configure_oauth_settings_reader(repo)
        self.assertEqual(resolve_oauth_config(env=_env()).enabled_providers, ("github",))

        # 缓存窗口内直接改行不可见
        repo._row = _row(enabled_providers="google")
        self.assertEqual(resolve_oauth_config(env=_env()).enabled_providers, ("github",))

        invalidate_oauth_config_cache()
        self.assertEqual(resolve_oauth_config(env=_env()).enabled_providers, ("google",))

    def test_configured_providers_requires_valid_base_url_and_secrets(self) -> None:
        repo = FakeOAuthSettingsRepository(
            _row(google_client_secret="", enabled_providers="github,google")
        )
        configure_oauth_settings_reader(repo)

        config = resolve_oauth_config(env=_env())

        # google 启用但缺 secret → 不出现在 configured_providers
        self.assertEqual(config.configured_providers, ("github",))

        repo._row = _row(public_base_url="not a url")
        invalidate_oauth_config_cache()
        self.assertEqual(resolve_oauth_config(env=_env()).configured_providers, ())


if __name__ == "__main__":
    unittest.main()
