"""第三方首登资料导入契约：昵称取 provider 显示名，头像仅新账户、尽力而为、不覆盖。"""

from __future__ import annotations

import asyncio
from io import BytesIO
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from backend.app.api import routes_oauth
from backend.app.api.dependencies import (
    get_oauth_identity_repository,
    get_user_account_repository,
)
from backend.app.repositories.oauth_identity_repository import OAuthLoginResolution
from backend.app.services.auth.avatar import MAX_AVATAR_BYTES
from backend.app.services.auth.oauth import avatar_import
from backend.app.services.auth.oauth.contracts import OAuthProfile
from backend.app.services.auth.oauth.runtime_config import EffectiveOAuthConfig

GITHUB_AVATAR = "https://avatars.githubusercontent.com/u/12345?v=4"
GOOGLE_AVATAR = "https://lh3.googleusercontent.com/a/abc=s96-c"


def _jpeg() -> bytes:
    output = BytesIO()
    Image.new("RGB", (64, 48), (200, 30, 30)).save(output, format="JPEG")
    return output.getvalue()


def _factory(handler):
    def factory(**kwargs):
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs)

    return factory


class RecordingUsers:
    def __init__(self, rowcount: int = 1) -> None:
        self.rowcount = rowcount
        self.writes: list[dict[str, Any]] = []

    def set_initial_user_avatar(self, **kwargs: Any) -> int:
        self.writes.append(kwargs)
        return self.rowcount

    def get_user_by_id(self, user_id: int):
        return None


# ---------------------------------------------------------------------------
# 头像来源白名单
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("url", [GITHUB_AVATAR, GOOGLE_AVATAR, "https://q.qlogo.cn/a", "https://thirdqq.qlogo.cn/a", "https://linux.do/user_avatar/a"])
def test_provider_avatar_hosts_are_allowed(url: str) -> None:
    assert avatar_import.provider_avatar_url_allowed(url)


@pytest.mark.parametrize(
    "url",
    [
        None, "",
        "http://avatars.githubusercontent.com/u/1",
        "https://avatars.githubusercontent.com:8443/u/1",
        "https://user@avatars.githubusercontent.com/u/1",
        "https://evil.test/u/1",
        "https://q.qlogo.cn.evil.test/a",
        "https://linux.do.evil.test/a",
        "https://linux.do:invalid/a",
        "https://[broken/avatar",
        "https://q.qlogo.cn@127.0.0.1/a",
        "https://avatars.githubusercontent.com.evil.test/u/1",
        "https://evilgoogleusercontent.com/a",
        "https://127.0.0.1/avatar.png",
        "https://thirdwx.qlogo.cn/mmopen/x/132",
        "https://avatars.githubusercontent.com/u/1 x",
        "https://avatars.githubusercontent.com/" + "a" * 2100,
    ],
)
def test_other_avatar_sources_are_rejected(url: str | None) -> None:
    assert not avatar_import.provider_avatar_url_allowed(url)


# ---------------------------------------------------------------------------
# 拉取与落库
# ---------------------------------------------------------------------------


def test_import_normalizes_and_writes_only_via_initial_avatar() -> None:
    users = RecordingUsers()
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, content=_jpeg())

    written = asyncio.run(avatar_import.import_provider_avatar(
        user_id=7, url=GITHUB_AVATAR, users=users, client_factory=_factory(handler),
    ))

    assert written is True
    assert seen == [GITHUB_AVATAR]
    [write] = users.writes
    assert write["user_id"] == 7
    assert write["png"].startswith(b"\x89PNG")
    with Image.open(BytesIO(write["png"])) as image:
        assert image.size == (256, 256)
    assert len(write["digest"]) == 64


def test_import_reports_false_when_account_already_has_avatar() -> None:
    users = RecordingUsers(rowcount=0)

    written = asyncio.run(avatar_import.import_provider_avatar(
        user_id=7, url=GITHUB_AVATAR, users=users,
        client_factory=_factory(lambda request: httpx.Response(200, content=_jpeg())),
    ))

    assert written is False
    assert len(users.writes) == 1


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(404),
        httpx.Response(302, headers={"location": "https://evil.test/a.png"}),
        httpx.Response(200, content=b"not an image"),
        httpx.Response(200, content=b"\xff" * (MAX_AVATAR_BYTES + 1)),
    ],
)
def test_import_skips_bad_responses_without_writing(response: httpx.Response) -> None:
    users = RecordingUsers()
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        return response

    written = asyncio.run(avatar_import.import_provider_avatar(
        user_id=7, url=GITHUB_AVATAR, users=users, client_factory=_factory(handler),
    ))

    assert written is False
    assert users.writes == []
    assert requests == [GITHUB_AVATAR]  # 重定向不跟随


def test_import_never_raises_on_transport_failure() -> None:
    users = RecordingUsers()

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timeout", request=request)

    written = asyncio.run(avatar_import.import_provider_avatar(
        user_id=7, url=GITHUB_AVATAR, users=users, client_factory=_factory(handler),
    ))

    assert written is False
    assert users.writes == []


def test_disallowed_url_is_never_fetched() -> None:
    users = RecordingUsers()

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - 不应被调用
        raise AssertionError("disallowed avatar URL was fetched")

    written = asyncio.run(avatar_import.import_provider_avatar(
        user_id=7, url="https://evil.test/a.png", users=users, client_factory=_factory(handler),
    ))

    assert written is False
    assert users.writes == []


# ---------------------------------------------------------------------------
# 登录回调：昵称与头像调度
# ---------------------------------------------------------------------------


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    async def set(self, key: str, value: str, *, ex: int) -> None:
        self.values[key] = value

    async def getdel(self, key: str):
        return self.values.pop(key, None)


class FakeIdentities:
    def __init__(self, *, created: bool) -> None:
        self.created = created
        self.resolve_calls: list[dict[str, Any]] = []

    def resolve_first_login(self, **kwargs: Any) -> OAuthLoginResolution:
        self.resolve_calls.append(kwargs)
        return OAuthLoginResolution(
            status="authenticated",
            user={"id": 7, "role": "user", "pwd_ver": 1},
            created=self.created,
        )


class FakeAdapter:
    use_pkce = True
    use_nonce = False

    def __init__(self, profile: OAuthProfile) -> None:
        self.profile = profile

    def authorization_url(self, *, state: str, redirect_uri: str, **kwargs: Any) -> str:
        return f"https://provider.test/authorize?state={state}"

    async def exchange_code(self, **kwargs: Any) -> OAuthProfile:
        return self.profile


def _config() -> EffectiveOAuthConfig:
    return EffectiveOAuthConfig(
        enabled_providers=(), public_base_url="https://example.test",
        github_client_id="", github_client_secret="", google_client_id="",
        google_client_secret="", wechat_app_id="", wechat_app_secret="",
        state_ttl_seconds=300, handoff_ttl_seconds=120, source="unconfigured",
    )


def _login(
    monkeypatch: pytest.MonkeyPatch, *, profile: OAuthProfile, created: bool
) -> tuple[httpx.Response, FakeIdentities, list[dict[str, Any]]]:
    identities = FakeIdentities(created=created)
    users = RecordingUsers()
    imports: list[dict[str, Any]] = []

    async def record_import(**kwargs: Any) -> bool:
        imports.append(kwargs)
        return True

    app = FastAPI()
    app.state.redis = FakeRedis()
    app.include_router(routes_oauth.router, prefix="/api")
    app.dependency_overrides[get_user_account_repository] = lambda: users
    app.dependency_overrides[get_oauth_identity_repository] = lambda: identities
    monkeypatch.setattr(routes_oauth, "_config", lambda request: _config())
    monkeypatch.setattr(routes_oauth, "configured_oauth_providers", lambda **kwargs: ["github"])
    monkeypatch.setattr(
        routes_oauth, "build_oauth_adapters", lambda config: {"github": FakeAdapter(profile)}
    )
    monkeypatch.setattr(routes_oauth, "import_provider_avatar", record_import)
    client = TestClient(app, base_url="https://example.test")
    start = client.get("/api/auth/oauth/github/start", follow_redirects=False)
    state = start.headers["location"].split("state=", 1)[1]
    callback = client.get(
        "/api/auth/oauth/github/callback",
        params={"code": "code", "state": state},
        follow_redirects=False,
    )
    for call in imports:
        assert call["users"] is users
    return callback, identities, imports


def _profile(**overrides: Any) -> OAuthProfile:
    values: dict[str, Any] = {
        "provider_subject": "12345", "email": "octo@example.test", "email_verified": True,
        "username": "octocat", "display_name": "The Octocat", "avatar_url": GITHUB_AVATAR,
    }
    values.update(overrides)
    return OAuthProfile(**values)


def test_new_account_gets_display_name_and_background_avatar_import(monkeypatch) -> None:
    callback, identities, imports = _login(monkeypatch, profile=_profile(), created=True)

    assert callback.status_code == 303
    assert identities.resolve_calls[0]["username"] == "The Octocat"
    assert [(call["user_id"], call["url"]) for call in imports] == [(7, GITHUB_AVATAR)]


def test_blank_display_name_falls_back_to_provider_username(monkeypatch) -> None:
    _, identities, _ = _login(monkeypatch, profile=_profile(display_name="  "), created=True)

    assert identities.resolve_calls[0]["username"] == "octocat"


def test_returning_account_never_imports_avatar(monkeypatch) -> None:
    callback, _, imports = _login(monkeypatch, profile=_profile(), created=False)

    assert callback.status_code == 303
    assert imports == []


@pytest.mark.parametrize("url", ["", "https://evil.test/a.png"])
def test_missing_or_foreign_avatar_is_not_scheduled(monkeypatch, url: str) -> None:
    callback, _, imports = _login(monkeypatch, profile=_profile(avatar_url=url), created=True)

    assert callback.status_code == 303
    assert imports == []

