from __future__ import annotations

from dataclasses import asdict

import pytest

from backend.app.services.auth.oauth.config_admin import OAuthConfigAdminService
from backend.app.services.auth.oauth.registry import configured_oauth_providers, get_oauth_provider_config
from backend.app.services.auth.oauth.runtime_config import (
    configure_oauth_settings_reader,
    reset_oauth_config_provider,
    resolve_oauth_config,
)
from backend.app.services.auth.oauth.service import build_oauth_adapters
from backend.tests.test_oauth_config_admin import FakeOAuthSettingsRepository, _env, _row
from backend.tests.test_qq_linuxdo_oauth import PROVIDERS


@pytest.fixture(autouse=True)
def reset_runtime():
    reset_oauth_config_provider()
    yield
    reset_oauth_config_provider()


@pytest.mark.parametrize("provider", PROVIDERS)
def test_env_configuration_requires_enable_credentials_base_url_and_redis(provider):
    env = _env(oauth_enabled_providers=provider, **{
        f"{provider}_oauth_client_id": "app-id", f"{provider}_oauth_client_secret": "app-secret",
    })
    config = resolve_oauth_config(env=env)
    assert configured_oauth_providers(config=config, redis_available=True) == [provider]
    assert configured_oauth_providers(config=config, redis_available=False) == []
    assert isinstance(build_oauth_adapters(config)[provider], PROVIDERS[provider])
    assert get_oauth_provider_config(provider, config=config).client_id == "app-id"
    for missing in ("oauth_enabled_providers", "public_base_url", f"{provider}_oauth_client_id", f"{provider}_oauth_client_secret"):
        original = getattr(env, missing)
        setattr(env, missing, "")
        assert resolve_oauth_config(env=env).configured_providers == ()
        setattr(env, missing, original)


@pytest.mark.anyio
@pytest.mark.parametrize("provider", PROVIDERS)
async def test_new_secrets_are_masked_retained_and_explicitly_clearable(provider):
    secret = f"{provider}-secret-for-encrypted-storage"
    repo = FakeOAuthSettingsRepository(_row())
    configure_oauth_settings_reader(repo)
    service = OAuthConfigAdminService(repo, env_config=_env())
    values = {"enabled_providers": [provider], "public_base_url": "https://example.test",
              f"{provider}_client_id": "app-id", f"{provider}_client_secret": secret}
    projection = await service.update_config(values)
    assert secret not in str(asdict(projection))
    assert getattr(projection, f"{provider}_client_secret_configured")
    assert resolve_oauth_config().configured_providers == (provider,)
    values[f"{provider}_client_secret"] = None
    await service.update_config(values)
    assert getattr(repo.get_oauth_settings(), f"{provider}_client_secret") == secret
    values[f"clear_{provider}_client_secret"] = True
    projection = await service.update_config(values)
    assert not getattr(projection, f"{provider}_client_secret_configured")
    assert resolve_oauth_config().configured_providers == ()


@pytest.mark.parametrize("provider", PROVIDERS)
def test_admin_api_accepts_new_provider_fields_without_returning_secrets(provider):
    from backend.tests.test_routes_ops_oauth import _client

    repo = FakeOAuthSettingsRepository()
    configure_oauth_settings_reader(repo)
    client = _client(repo)
    secret = f"{provider}-only-in-request-secret"
    response = client.put("/api/ops/oauth/config", json={
        "enabled_providers": [provider], "public_base_url": "https://example.test",
        f"{provider}_client_id": "app-id", f"{provider}_client_secret": secret,
    })
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json()[f"{provider}_client_id"] == "app-id"
    assert response.json()[f"{provider}_client_secret_configured"] is True
    assert secret not in response.text and secret not in client.get("/api/ops/oauth/config").text
