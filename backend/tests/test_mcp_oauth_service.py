"""MCP OAuth 纯逻辑：回调地址校验与匹配、PKCE、资源标识、客户端名称、授权码存储。"""

from __future__ import annotations

import hashlib
import json
import unittest

import pytest

from backend.app.services.auth import mcp_oauth
from backend.app.services.auth.mcp_oauth import (
    MCP_OAUTH_RESOURCE,
    AuthorizationCodePayload,
    AuthorizationCodeStore,
    InvalidRedirectUriError,
    McpOAuthUnavailableError,
    canonical_resource,
    client_secret_matches,
    describe_redirect_uri,
    hash_client_secret,
    infer_client_type,
    new_client_id,
    new_client_secret,
    normalize_client_name,
    pkce_s256_challenge,
    redirect_uri_registered,
    redirect_with_params,
    validate_redirect_uri,
    verify_pkce_s256,
)


def test_issuer_and_resource_are_the_canonical_site() -> None:
    # 前端静态元数据（RFC 8414 / RFC 9728）与 Go 401 头里的地址都以这两个常量为准
    assert mcp_oauth.MCP_OAUTH_ISSUER == "https://aigcnews.cn"
    assert MCP_OAUTH_RESOURCE == "https://aigcnews.cn/api/mcp/oauth"


@pytest.mark.parametrize(
    "uri",
    [
        "http://localhost:33418/callback",
        "http://127.0.0.1:5000/cb?x=1",
        "http://[::1]:8080/cb",
        "http://localhost/callback",
        "https://claude.ai/api/mcp/auth_callback",
        "https://vscode.dev/redirect",
        "cursor://anysphere.cursor-retrieval/oauth/user-defined-mcp/callback",
        "com.example.app:/oauth2redirect",
    ],
)
def test_redirect_uri_accepts_web_loopback_and_app_callbacks(uri: str) -> None:
    assert validate_redirect_uri(uri) == uri


@pytest.mark.parametrize(
    "uri",
    [
        None,
        "",
        42,
        "relative/callback",
        "/callback",
        "http://evil.example/cb",
        "http://localhost.evil.example/cb",
        "javascript:alert(1)",
        "JavaScript:alert(1)",
        "data:text/html,<script>alert(1)</script>",
        "file:///etc/passwd",
        "vbscript:msgbox",
        " https://example.com/cb",
        "https://example.com/c b",
        "https://example.com/cb#frag",
        "https://user@example.com/cb",
        "https://example.com\\@evil.example/cb",
        "https:///no-host",
        "https:no-host",
        "http://localhost:99999/cb",
        "http://[::1/cb",
        "https://例子.cn/cb",
        "https://example.com/" + "a" * 2000,
    ],
)
def test_redirect_uri_rejects_unsafe_or_ambiguous_values(uri: object) -> None:
    with pytest.raises(InvalidRedirectUriError):
        validate_redirect_uri(uri)


def test_registered_redirect_matches_exactly_except_loopback_port() -> None:
    registered = [
        "http://localhost:1234/callback",
        "https://app.example/cb",
        "cursor://anysphere.cursor-retrieval/cb",
    ]
    assert redirect_uri_registered(registered, "https://app.example/cb")
    assert redirect_uri_registered(registered, "cursor://anysphere.cursor-retrieval/cb")
    # RFC 8252 §7.3：回环地址每次可换端口
    assert redirect_uri_registered(registered, "http://localhost:5678/callback")
    assert redirect_uri_registered(registered, "http://localhost/callback")
    # 主机、路径、查询必须一致；回环之外端口也必须一致
    assert not redirect_uri_registered(registered, "http://127.0.0.1:1234/callback")
    assert not redirect_uri_registered(registered, "http://localhost:1234/callback/")
    assert not redirect_uri_registered(registered, "http://localhost:1234/callback?x=1")
    assert not redirect_uri_registered(registered, "https://app.example:8443/cb")
    assert not redirect_uri_registered(registered, "https://app.example/cb2")
    assert not redirect_uri_registered(registered, "https://localhost:1234/callback")


def test_describe_redirect_uri_reports_kind_and_host() -> None:
    assert describe_redirect_uri("http://localhost:1/cb") == {"kind": "loopback", "host": "localhost"}
    assert describe_redirect_uri("https://Claude.ai/api/mcp/auth_callback") == {
        "kind": "web",
        "host": "claude.ai",
    }
    assert describe_redirect_uri("cursor://anysphere.cursor-retrieval/cb") == {
        "kind": "app",
        "host": "cursor:",
    }


def test_redirect_with_params_preserves_existing_query_and_encodes_values() -> None:
    params = {"code": "abc", "state": "a b&c/d", "iss": "https://aigcnews.cn", "skip": None}
    assert redirect_with_params("https://app.example/cb", params) == (
        "https://app.example/cb?code=abc&state=a%20b%26c%2Fd&iss=https%3A%2F%2Faigcnews.cn"
    )
    assert redirect_with_params("https://app.example/cb?keep=1", {"code": "x"}) == (
        "https://app.example/cb?keep=1&code=x"
    )
    assert redirect_with_params("https://app.example/cb?", {"code": "x"}) == "https://app.example/cb?code=x"
    assert redirect_with_params("com.example.app:/cb", {"code": "x"}) == "com.example.app:/cb?code=x"
    assert redirect_with_params("https://app.example/cb", {"state": None}) == "https://app.example/cb"


def test_pkce_s256_matches_rfc7636_appendix_b_vector() -> None:
    verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    challenge = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
    assert pkce_s256_challenge(verifier) == challenge
    assert verify_pkce_s256(verifier, challenge)
    assert not verify_pkce_s256(verifier[:-1] + "Y", challenge)
    # 校验器长度 43–128、字符集为 unreserved；挑战值必须是 43 位 base64url
    assert not verify_pkce_s256("short", pkce_s256_challenge("short"))
    assert not verify_pkce_s256("a" * 129, pkce_s256_challenge("a" * 129))
    assert not verify_pkce_s256(verifier, challenge + "=")
    assert not verify_pkce_s256(None, challenge)


def test_canonical_resource_only_accepts_this_mcp_endpoint() -> None:
    assert canonical_resource(None) == MCP_OAUTH_RESOURCE
    assert canonical_resource("") == MCP_OAUTH_RESOURCE
    assert canonical_resource(MCP_OAUTH_RESOURCE) == MCP_OAUTH_RESOURCE
    assert canonical_resource(MCP_OAUTH_RESOURCE + "/") == MCP_OAUTH_RESOURCE
    assert canonical_resource("https://aigcnews.cn/api/mcp") is None
    assert canonical_resource("https://evil.example/api/mcp/oauth") is None
    assert canonical_resource("https://aigcnews.cn") is None


def test_client_name_strips_invisible_characters_and_truncates() -> None:
    assert normalize_client_name("  Claude\tCode \n (aigc-news) ") == "Claude Code (aigc-news)"
    # 双向文本控制符会让同意页上的名字显示成别的样子
    assert normalize_client_name("Safe‮edoC") == "Safe edoC"
    assert normalize_client_name("x" * 300) == "x" * 128
    assert normalize_client_name(None) == ""
    assert normalize_client_name(["Claude"]) == ""


def test_client_type_follows_self_declared_name() -> None:
    assert infer_client_type("Claude Code (aigc-news)") == "claude"
    assert infer_client_type("claude.ai") == "claude"
    assert infer_client_type("Cursor") == "cursor"
    assert infer_client_type("Visual Studio Code") == "vscode"
    assert infer_client_type("VS Code") == "vscode"
    assert infer_client_type("MCP Inspector") == "other"
    assert infer_client_type("") == "other"


def test_client_credentials_are_random_and_secrets_compare_by_digest() -> None:
    client_id = new_client_id()
    assert client_id.startswith("aigc_oc_") and len(client_id) <= 64
    assert new_client_id() != client_id
    secret = new_client_secret()
    assert secret.startswith("aigc_ocs_")
    digest = hash_client_secret(secret)
    assert digest == hashlib.sha256(secret.encode()).hexdigest()
    assert client_secret_matches(secret, digest)
    assert not client_secret_matches(secret + "x", digest)
    assert not client_secret_matches(None, digest)
    assert not client_secret_matches(secret, None)


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.ttls: dict[str, int] = {}

    async def set(self, key: str, value: str, *, ex: int) -> None:
        self.values[key] = value
        self.ttls[key] = ex

    async def getdel(self, key: str):
        return self.values.pop(key, None)


class LuaOnlyRedis(FakeRedis):
    getdel = None  # 老 Redis 没有 GETDEL：走 Lua 原子取删

    async def eval(self, script: str, numkeys: int, key: str):
        assert "redis.call('DEL', KEYS[1])" in script and numkeys == 1
        return self.values.pop(key, None)


class BrokenRedis:
    async def set(self, *args, **kwargs):
        raise ConnectionError("redis down")

    async def getdel(self, key: str):
        raise ConnectionError("redis down")


def _payload() -> AuthorizationCodePayload:
    return AuthorizationCodePayload(
        client_id="aigc_oc_client",
        client_name="Claude Code",
        user_id=7,
        redirect_uri="http://localhost:1234/callback",
        code_challenge="E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM",
        scopes=["projects:favorites:read", "tracking:read"],
        resource=MCP_OAUTH_RESOURCE,
    )


class AuthorizationCodeStoreTests(unittest.IsolatedAsyncioTestCase):
    async def test_code_is_single_use_and_stored_under_digest_with_ttl(self) -> None:
        redis = FakeRedis()
        store = AuthorizationCodeStore(redis)
        code = await store.issue(_payload())

        (key,) = redis.values
        self.assertEqual(key, "auth:mcp-oauth:code:" + hashlib.sha256(code.encode()).hexdigest())
        self.assertNotIn(code, key)
        self.assertNotIn(code, redis.values[key])
        self.assertEqual(redis.ttls[key], 300)
        self.assertEqual(json.loads(redis.values[key])["user_id"], 7)

        self.assertEqual(await store.consume(code), _payload())
        self.assertIsNone(await store.consume(code))

    async def test_unknown_oversized_or_corrupt_codes_are_rejected(self) -> None:
        redis = FakeRedis()
        store = AuthorizationCodeStore(redis)
        self.assertIsNone(await store.consume("missing"))
        self.assertIsNone(await store.consume(""))
        self.assertIsNone(await store.consume(None))
        self.assertIsNone(await store.consume("x" * 513))
        redis.values[mcp_oauth.authorization_code_key("bad")] = '{"user_id": "not-a-number"}'
        self.assertIsNone(await store.consume("bad"))

    async def test_lua_fallback_keeps_single_use(self) -> None:
        redis = LuaOnlyRedis()
        store = AuthorizationCodeStore(redis)
        code = await store.issue(_payload())
        self.assertEqual(await store.consume(code), _payload())
        self.assertIsNone(await store.consume(code))

    async def test_missing_or_failing_redis_fails_closed(self) -> None:
        with self.assertRaises(McpOAuthUnavailableError):
            await AuthorizationCodeStore(None).issue(_payload())
        with self.assertRaises(McpOAuthUnavailableError):
            await AuthorizationCodeStore(None).consume("code")
        with self.assertRaises(McpOAuthUnavailableError):
            await AuthorizationCodeStore(BrokenRedis()).issue(_payload())
        with self.assertRaises(McpOAuthUnavailableError):
            await AuthorizationCodeStore(BrokenRedis()).consume("code")
