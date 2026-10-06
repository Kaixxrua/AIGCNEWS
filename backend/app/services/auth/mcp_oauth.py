"""MCP OAuth 授权服务器：远程 MCP 客户端用浏览器登录本站换令牌。

按 MCP Authorization 规范接入（Claude Code、Claude.ai、Cursor、VS Code 等）：

- 受保护资源元数据（RFC 9728）与授权服务器元数据（RFC 8414）是前端静态文件，
  其中的 issuer 与 resource 必须与本模块常量逐字一致；
- 动态客户端注册（RFC 7591）；授权码 + PKCE S256（RFC 7636，所有客户端强制）；
- resource 参数（RFC 8707）只能指向本站 MCP OAuth 端点；授权响应带 iss（RFC 9207）。

签发的令牌就是 user_mcp_tokens 的普通行：Go 侧鉴权不变，用户在 /mcp 页面能看到并删除。
本模块只放无 I/O 的校验逻辑和授权码的 Redis 存储；Redis 不可用时一律失败（fail closed）。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
from collections.abc import Iterable
from typing import Any
from urllib.parse import quote, urlencode, urlsplit

from pydantic import BaseModel, ConfigDict, ValidationError

MCP_OAUTH_ISSUER = "https://aigcnews.cn"
MCP_OAUTH_RESOURCE = f"{MCP_OAUTH_ISSUER}/api/mcp/oauth"

CLIENT_ID_PREFIX = "aigc_oc_"
CLIENT_SECRET_PREFIX = "aigc_ocs_"
TOKEN_ENDPOINT_AUTH_METHODS = ("none", "client_secret_post", "client_secret_basic")

MAX_REDIRECT_URIS = 10
MAX_REDIRECT_URI_LENGTH = 2000
MAX_CLIENT_NAME_LENGTH = 128
MAX_STATE_LENGTH = 2048

AUTHORIZATION_CODE_TTL_SECONDS = 300
AUTHORIZATION_CODE_KEY_PREFIX = "auth:mcp-oauth:code:"

_LOOPBACK_HOSTNAMES = frozenset({"localhost", "127.0.0.1", "::1"})
_SCHEME_RE = re.compile(r"[a-z][a-z0-9+.\-]*")
# 浏览器内导航会在本站执行脚本或读本地内容的协议，以及明显不是应用回调的协议。
# 其余私有协议（cursor://、vscode:// 等）交给操作系统打开，浏览器会先问用户。
_BLOCKED_SCHEMES = frozenset(
    {
        "about",
        "blob",
        "data",
        "file",
        "filesystem",
        "ftp",
        "intent",
        "javascript",
        "mailto",
        "sms",
        "tel",
        "vbscript",
        "view-source",
        "ws",
        "wss",
    }
)
_CODE_VERIFIER_RE = re.compile(r"[A-Za-z0-9\-._~]{43,128}")
_CODE_CHALLENGE_RE = re.compile(r"[A-Za-z0-9_\-]{43}")


class InvalidRedirectUriError(ValueError):
    """Redirect URI is not acceptable for registration or authorization."""


class McpOAuthUnavailableError(RuntimeError):
    """Redis is unavailable, so MCP OAuth must fail closed."""


# ---------------------------------------------------------------- redirect URIs


def validate_redirect_uri(uri: Any) -> str:
    """校验回调地址并原样返回；不合规抛 InvalidRedirectUriError。

    - 只收可打印 ASCII（不含空白、反斜杠），协议名小写：杜绝浏览器与本服务解析不一致；
    - https 任意主机；http 只允许本机回环（RFC 8252 §7.3）；
    - 私有协议（RFC 8252 §7.1）放行，危险协议拒绝；
    - 不能带片段（RFC 6749 §3.1.2）和用户信息。
    """
    if not isinstance(uri, str) or not uri or len(uri) > MAX_REDIRECT_URI_LENGTH:
        raise InvalidRedirectUriError("redirect_uri 为空或过长")
    if any(not 0x21 <= ord(char) <= 0x7E for char in uri) or "\\" in uri:
        raise InvalidRedirectUriError("redirect_uri 只能是不含空白和反斜杠的 ASCII")
    scheme, separator, rest = uri.partition(":")
    if not separator or not rest or not _SCHEME_RE.fullmatch(scheme):
        raise InvalidRedirectUriError("redirect_uri 必须是带小写协议名的绝对地址")
    if scheme in _BLOCKED_SCHEMES:
        raise InvalidRedirectUriError(f"不允许 {scheme} 协议的回调地址")
    if "#" in uri:
        raise InvalidRedirectUriError("redirect_uri 不能带片段")
    try:
        parts = urlsplit(uri)
        parts.port
    except ValueError as exc:
        raise InvalidRedirectUriError("redirect_uri 主机或端口不合法") from exc
    if "@" in parts.netloc:
        raise InvalidRedirectUriError("redirect_uri 不能带用户信息")
    if scheme in ("http", "https"):
        if not rest.startswith("//") or not parts.hostname:
            raise InvalidRedirectUriError("redirect_uri 缺少主机名")
        if scheme == "http" and parts.hostname not in _LOOPBACK_HOSTNAMES:
            raise InvalidRedirectUriError("http 回调只允许本机回环地址")
    return uri


def _loopback_key(uri: str) -> tuple[str, str, str, str] | None:
    try:
        parts = urlsplit(uri)
        parts.port
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or parts.hostname not in _LOOPBACK_HOSTNAMES:
        return None
    return parts.scheme, parts.hostname, parts.path, parts.query


def redirect_uri_registered(registered: Iterable[str], requested: str) -> bool:
    """逐字匹配已登记的回调地址；本机回环地址不比端口（RFC 8252 §7.3）。

    调用方须先用 validate_redirect_uri 校验 requested。
    """
    candidates = list(registered)
    if requested in candidates:
        return True
    key = _loopback_key(requested)
    return key is not None and any(_loopback_key(item) == key for item in candidates)


def describe_redirect_uri(uri: str) -> dict[str, str]:
    """同意页展示用：回调去向的类别与主机（私有协议显示协议名）。"""
    parts = urlsplit(uri)
    if parts.scheme in ("http", "https"):
        kind = "loopback" if parts.hostname in _LOOPBACK_HOSTNAMES else "web"
        return {"kind": kind, "host": parts.hostname or ""}
    return {"kind": "app", "host": f"{parts.scheme}:"}


def redirect_with_params(uri: str, params: dict[str, str | None]) -> str:
    """把授权响应参数追加到回调地址的查询串，保留地址里原有的查询参数。"""
    encoded = urlencode(
        [(key, value) for key, value in params.items() if value is not None],
        quote_via=quote,
    )
    if not encoded:
        return uri
    if "?" not in uri:
        return f"{uri}?{encoded}"
    if uri.endswith(("?", "&")):
        return f"{uri}{encoded}"
    return f"{uri}&{encoded}"


# ---------------------------------------------------------------- PKCE / client


def is_valid_code_challenge(value: Any) -> bool:
    return isinstance(value, str) and _CODE_CHALLENGE_RE.fullmatch(value) is not None


def is_valid_code_verifier(value: Any) -> bool:
    return isinstance(value, str) and _CODE_VERIFIER_RE.fullmatch(value) is not None


def pkce_s256_challenge(code_verifier: str) -> str:
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def verify_pkce_s256(code_verifier: Any, code_challenge: str) -> bool:
    if not is_valid_code_verifier(code_verifier) or not is_valid_code_challenge(code_challenge):
        return False
    return hmac.compare_digest(pkce_s256_challenge(code_verifier), code_challenge)


def canonical_resource(value: str | None) -> str | None:
    """返回规范的资源标识；指向别的资源时返回 None（RFC 8707 invalid_target）。

    不带 resource 的旧客户端按本站 MCP OAuth 端点处理；末尾斜杠视为同一资源。
    """
    if value is None or value == "":
        return MCP_OAUTH_RESOURCE
    if value.rstrip("/") == MCP_OAUTH_RESOURCE:
        return MCP_OAUTH_RESOURCE
    return None


def normalize_client_name(value: Any) -> str:
    """客户端自报的名称：去掉控制符与双向文本等不可见字符，折叠空白并截断。"""
    if not isinstance(value, str):
        return ""
    cleaned = "".join(char if char.isprintable() else " " for char in value)
    return " ".join(cleaned.split())[:MAX_CLIENT_NAME_LENGTH]


def infer_client_type(client_name: str) -> str:
    """按客户端自报名称归入 /mcp 页面的客户端类别；只影响展示，不影响权限。"""
    lowered = client_name.casefold()
    for needle, client_type in (
        ("claude", "claude"),
        ("cursor", "cursor"),
        ("vscode", "vscode"),
        ("vs code", "vscode"),
        ("visual studio code", "vscode"),
    ):
        if needle in lowered:
            return client_type
    return "other"


def new_client_id() -> str:
    return CLIENT_ID_PREFIX + secrets.token_urlsafe(24)


def new_client_secret() -> str:
    return CLIENT_SECRET_PREFIX + secrets.token_urlsafe(32)


def hash_client_secret(client_secret: str) -> str:
    return hashlib.sha256(client_secret.encode("utf-8")).hexdigest()


def client_secret_matches(client_secret: str | None, expected_hash: str | None) -> bool:
    if not client_secret or not expected_hash:
        return False
    return hmac.compare_digest(hash_client_secret(client_secret), expected_hash)


# ---------------------------------------------------------------- authorization codes


class AuthorizationCodePayload(BaseModel):
    """授权码绑定的全部上下文；换令牌时逐项核对。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    client_id: str
    client_name: str
    user_id: int
    redirect_uri: str
    code_challenge: str
    scopes: list[str]
    resource: str


def authorization_code_key(code: str) -> str:
    return AUTHORIZATION_CODE_KEY_PREFIX + hashlib.sha256(code.encode("utf-8")).hexdigest()


class AuthorizationCodeStore:
    """一次性授权码：Redis 里只存摘要做键，GETDEL 原子消费，默认 5 分钟过期。"""

    def __init__(
        self,
        redis_client: Any,
        *,
        ttl_seconds: int = AUTHORIZATION_CODE_TTL_SECONDS,
    ) -> None:
        self._redis = redis_client
        self._ttl_seconds = ttl_seconds

    async def issue(self, payload: AuthorizationCodePayload) -> str:
        if self._redis is None:
            raise McpOAuthUnavailableError
        code = secrets.token_urlsafe(32)
        try:
            await self._redis.set(
                authorization_code_key(code), payload.model_dump_json(), ex=self._ttl_seconds
            )
        except Exception as exc:
            raise McpOAuthUnavailableError from exc
        return code

    async def consume(self, code: Any) -> AuthorizationCodePayload | None:
        """取出并作废授权码；不存在、过期、已用过或数据损坏都返回 None。"""
        if self._redis is None:
            raise McpOAuthUnavailableError
        if not isinstance(code, str) or not code or len(code) > 512:
            return None
        try:
            value = await self._getdel(authorization_code_key(code))
        except Exception as exc:
            raise McpOAuthUnavailableError from exc
        if value is None:
            return None
        try:
            if isinstance(value, bytes):
                value = value.decode("utf-8")
            return AuthorizationCodePayload.model_validate_json(value)
        except (UnicodeDecodeError, ValidationError, ValueError):
            return None

    async def _getdel(self, key: str) -> Any:
        getdel = getattr(self._redis, "getdel", None)
        if getdel is not None:
            return await getdel(key)
        # 与 OAuthStateStore 同法：没有 GETDEL 的 Redis 用服务端 Lua 保证一次性消费
        return await self._redis.eval(
            "local value = redis.call('GET', KEYS[1]); "
            "if value then redis.call('DEL', KEYS[1]); end; return value",
            1,
            key,
        )
