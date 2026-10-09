from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

import pytest
from psycopg.errors import CheckViolation

from backend.app.domain.wechat_secret_box import WeChatSecretBox
from backend.app.repositories.postgres_oauth_identity_repository import PostgresOAuthIdentityRepository
from backend.app.repositories.postgres_oauth_settings_repository import (
    OAuthSettingsSecretError,
    PostgresOAuthSettingsRepository,
)
from backend.tests.postgres_test_safety import postgres_test_sandbox
from backend.tests.test_oauth_config_admin import _row


@pytest.fixture
def database():
    with postgres_test_sandbox() as sandbox:
        yield sandbox.database


@pytest.mark.parametrize("provider", ["qq", "linuxdo"])
def test_new_subject_login_is_stable_and_cannot_move_between_users(database, provider):
    repo = PostgresOAuthIdentityRepository(database)
    first = repo.resolve_first_login(provider=provider, provider_subject="123", username="Reader")
    returning = repo.resolve_first_login(provider=provider, provider_subject="123", username="Renamed")
    assert first.created is True
    assert returning.user["id"] == first.user["id"]
    assert returning.user["email"] is None
    other = repo.resolve_first_login(provider=provider, provider_subject="456", username="Reader")
    assert other.user["id"] != first.user["id"]
    assert repo.bind_identity(user_id=other.user["id"], provider=provider, provider_subject="123").status == "owned_by_other"
    assert repo.bind_identity(user_id=first.user["id"], provider=provider, provider_subject="123").status == "already_bound"
    # A matching subject from a different platform is a separate identity.
    alternate = "linuxdo" if provider == "qq" else "qq"
    assert repo.bind_identity(user_id=first.user["id"], provider=alternate, provider_subject="123").status == "bound"
    assert repo.resolve_first_login(provider=alternate, provider_subject="123").user["id"] == first.user["id"]


def test_new_credentials_round_trip_encrypted_and_legacy_values_survive_migration(database):
    box = WeChatSecretBox.from_urlsafe_base64("AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=", "v1")
    repo = PostgresOAuthSettingsRepository(database, secret_box=box)
    legacy = asdict(_row())
    legacy.pop("updated_at")
    saved = repo.upsert_oauth_settings(**legacy)
    migration = Path(__file__).parents[1] / "migrations/postgres/0092_qq_linuxdo_oauth.sql"
    # Reapplying the additive migration must preserve the existing settings.
    with database.transaction() as connection:
        connection.execute(migration.read_text())
    retained = repo.get_oauth_settings()
    assert retained.github_client_secret == saved.github_client_secret
    assert retained.qq_client_secret == retained.linuxdo_client_secret == ""
    values = {**legacy, "enabled_providers": "qq,linuxdo",
              "qq_client_id": "qq-id", "qq_client_secret": "qq-secret-sensitive",
              "linuxdo_client_id": "linux-id", "linuxdo_client_secret": "linux-secret-sensitive"}
    saved = repo.upsert_oauth_settings(**values)
    assert saved.qq_client_id == "qq-id" and saved.linuxdo_client_id == "linux-id"
    assert repo.get_oauth_settings().qq_client_secret == values["qq_client_secret"]
    assert repo.get_oauth_settings().linuxdo_client_secret == values["linuxdo_client_secret"]
    with database.transaction() as connection:
        raw = connection.execute("SELECT * FROM oauth_settings WHERE id = 1").fetchone()
    assert values["qq_client_secret"] not in str(raw)
    assert values["linuxdo_client_secret"] not in str(raw)
    no_key = PostgresOAuthSettingsRepository(database, secret_box=None)
    assert no_key.get_oauth_settings().qq_client_secret == ""
    with pytest.raises(OAuthSettingsSecretError):
        no_key.upsert_oauth_settings(**values)
    assert repo.get_oauth_settings().linuxdo_client_secret == values["linuxdo_client_secret"]


def test_provider_constraint_still_rejects_unknown_platforms(database):
    repo = PostgresOAuthIdentityRepository(database)
    user_id = repo.resolve_first_login(provider="qq", provider_subject="test").user["id"]
    with pytest.raises(CheckViolation), database.transaction() as connection:
        connection.execute(
            "INSERT INTO user_oauth_identities (user_id, provider, provider_subject) VALUES (%s, 'untrusted', 'test')",
            (user_id,),
        )
