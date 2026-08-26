from __future__ import annotations

from typing import Any, Protocol


class FeedTokenManager(Protocol):
    """Manage the owner's single RSS feed token without exposing token hashes."""

    def get_or_create_feed_token(
        self,
        *,
        user_id: int,
        token_hash: str,
        token_hint: str,
        token_encrypted: str,
    ) -> dict[str, Any]: ...

    def rotate_feed_token(
        self,
        *,
        user_id: int,
        token_hash: str,
        token_hint: str,
        token_encrypted: str,
    ) -> dict[str, Any]: ...


class FeedTokenAuthenticator(Protocol):
    """Resolve the token owner's identity from a SHA-256 token digest."""

    def get_user_by_feed_token_hash(
        self,
        token_hash: str,
    ) -> dict[str, Any] | None: ...


class FeedTokenRepository(
    FeedTokenManager,
    FeedTokenAuthenticator,
    Protocol,
):
    """Combined RSS feed-token persistence boundary."""
