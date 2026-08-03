"""JWT 密钥启动守卫契约测试。

背景：生产环境曾使用随仓库公开的示例密钥（.env.example 默认值），
任何人都能离线伪造 admin token。守卫必须在该类配置下拒绝启动。
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from backend.app import main
from backend.app.core.auth import (
    KNOWN_INSECURE_JWT_SECRETS,
    MIN_JWT_SECRET_LENGTH,
    validate_jwt_secret,
)


class TestValidateJwtSecret:
    def test_rejects_empty_secret(self) -> None:
        with pytest.raises(RuntimeError, match="JWT_SECRET_KEY"):
            validate_jwt_secret("")

    @pytest.mark.parametrize("secret", sorted(KNOWN_INSECURE_JWT_SECRETS))
    def test_rejects_publicly_known_example_secrets(self, secret: str) -> None:
        with pytest.raises(RuntimeError, match="openssl rand"):
            validate_jwt_secret(secret)

    def test_rejects_short_secret(self) -> None:
        with pytest.raises(RuntimeError, match="长度不足"):
            validate_jwt_secret("x" * (MIN_JWT_SECRET_LENGTH - 1))

    def test_accepts_strong_random_secret(self) -> None:
        validate_jwt_secret("a" * MIN_JWT_SECRET_LENGTH)
        validate_jwt_secret("0123456789abcdef" * 4)

    def test_known_insecure_set_never_empty(self) -> None:
        # 防止有人把集合清空来"修"测试
        assert KNOWN_INSECURE_JWT_SECRETS


class TestLifespanStartupGuard:
    @staticmethod
    def _settings(secret: str) -> SimpleNamespace:
        return SimpleNamespace(
            project_semantic_search_enabled=False,
            scheduler_enabled=False,
            redis_host="localhost",
            redis_port=6379,
            redis_db=0,
            redis_password="",
            env="production",
            JWT_SECRET_KEY=secret,
        )

    def test_lifespan_aborts_before_postgres_open_on_default_secret(self) -> None:
        app = type("_App", (), {"state": type("_State", (), {})()})()

        async def run() -> None:
            with (
                patch.object(main, "settings", self._settings("change-me-in-production")),
                patch.object(main.postgres_database, "open") as postgres_open,
            ):
                with pytest.raises(RuntimeError, match="JWT_SECRET_KEY"):
                    async with main.lifespan(app):
                        pass
                postgres_open.assert_not_called()

        asyncio.run(run())

    def test_lifespan_aborts_on_missing_secret_attribute(self) -> None:
        app = type("_App", (), {"state": type("_State", (), {})()})()

        async def run() -> None:
            fake_settings = SimpleNamespace(env="production")  # 无 JWT_SECRET_KEY
            with (
                patch.object(main, "settings", fake_settings),
                patch.object(main.postgres_database, "open") as postgres_open,
            ):
                with pytest.raises(RuntimeError, match="JWT_SECRET_KEY"):
                    async with main.lifespan(app):
                        pass
                postgres_open.assert_not_called()

        asyncio.run(run())


class TestSettingsDefault:
    def test_settings_no_longer_ship_insecure_default(self) -> None:
        from backend.app.core.config import Settings

        field_default = Settings.model_fields["JWT_SECRET_KEY"].default
        assert field_default not in KNOWN_INSECURE_JWT_SECRETS
        assert field_default == ""
