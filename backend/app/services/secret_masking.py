from __future__ import annotations


def mask_token(token: str | None) -> str | None:
    """Return a masked preview of a secret token, or None if empty.

    Mirrors the masking rule used for MCP auth tokens and X cookies so that
    admin responses never return plaintext secrets.
    """
    if not token:
        return None
    if len(token) <= 8:
        return "****"
    return f"{token[:4]}****{token[-4:]}"
