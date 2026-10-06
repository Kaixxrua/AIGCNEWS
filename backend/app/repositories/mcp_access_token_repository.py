from __future__ import annotations

from typing import Any, Protocol


class McpAccessTokenManager(Protocol):
    """Manage owner-scoped MCP access tokens without exposing token hashes."""

    def create_user_mcp_token(
        self,
        *,
        user_id: int,
        token_hash: str,
        token_hint: str,
        scopes: list[str],
        client_type: str,
        client_label: str = "",
        expires_at: Any = None,
        oauth_client_id: str | None = None,
    ) -> dict[str, Any]: ...

    def list_user_mcp_tokens(
        self,
        *,
        user_id: int,
    ) -> list[dict[str, Any]]: ...

    def delete_user_mcp_token(
        self,
        *,
        user_id: int,
        token_id: int,
    ) -> bool: ...


class DshMcpTokenManager(Protocol):
    """Ensure/rotate the owner's single reusable DSH-purpose MCP token.

    与通用 create/list/delete 分离：DSH token 由服务端固定用途与客户端
    标识，明文以密封材料落库供跨刷新回显；ensure 幂等不吊销，rotate
    显式吊销全部活跃 DSH token（不影响 generic token）。
    """

    def ensure_user_dsh_mcp_token(
        self,
        *,
        user_id: int,
        token_hash: str,
        token_hint: str,
        token_encrypted: str,
        scopes: list[str],
        client_type: str,
        client_label: str,
    ) -> dict[str, Any]: ...

    def rotate_user_dsh_mcp_token(
        self,
        *,
        user_id: int,
        token_hash: str,
        token_hint: str,
        token_encrypted: str,
        scopes: list[str],
        client_type: str,
        client_label: str,
    ) -> dict[str, Any]: ...


class McpAccessTokenAuthenticator(Protocol):
    """Resolve an internal security context from a SHA-256 token digest."""

    def get_user_by_mcp_token_hash(
        self,
        token_hash: str,
    ) -> dict[str, Any] | None: ...


class McpOAuthClientStore(Protocol):
    """Dynamically registered MCP OAuth clients (RFC 7591).

    返回的客户端字典含库内 ``client_secret_hash``，只供令牌端点核验，不得外发。
    """

    def register_mcp_oauth_client(
        self,
        *,
        client_id: str,
        client_name: str,
        redirect_uris: list[str],
        token_endpoint_auth_method: str,
        client_secret_hash: str | None,
    ) -> dict[str, Any]: ...

    def get_mcp_oauth_client(self, client_id: str) -> dict[str, Any] | None: ...


class McpAccessTokenRepository(
    McpAccessTokenManager,
    McpAccessTokenAuthenticator,
    DshMcpTokenManager,
    McpOAuthClientStore,
    Protocol,
):
    """Combined internal MCP access-token persistence boundary."""
