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


class McpAccessTokenAuthenticator(Protocol):
    """Resolve an internal security context from a SHA-256 token digest."""

    def get_user_by_mcp_token_hash(
        self,
        token_hash: str,
    ) -> dict[str, Any] | None: ...


class McpAccessTokenRepository(
    McpAccessTokenManager,
    McpAccessTokenAuthenticator,
    Protocol,
):
    """Combined internal MCP access-token persistence boundary."""
