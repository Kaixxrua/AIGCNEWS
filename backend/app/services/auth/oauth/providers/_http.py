"""HTTP helpers for OAuth provider adapters."""
from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import Any

import anyio
import httpx

_MAX_RESPONSE_BYTES = 1_048_576
_TIMEOUT = httpx.Timeout(10.0, connect=5.0)


class OAuthUpstreamError(RuntimeError):
    """Only fixed, non-sensitive messages may cross the callback boundary."""


async def request_with_retry(
    client: httpx.AsyncClient, method: str, url: str, **kwargs: Any,
) -> httpx.Response:
    """Retry once without replaying a possibly consumed authorization code.

    Connect/proxy setup failures occur before the request is sent. Read failures may be
    retried only for GETs; a token POST may already have consumed its code.
    Keep the supplied client's proxy, TLS, timeout and redirect policy.
    """
    try:
        return await client.request(method, url, **kwargs)
    except httpx.TransportError as exc:
        before_send = isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout, httpx.ProxyError))
        safe_read = method == "GET" and isinstance(
            exc, (httpx.ReadError, httpx.ReadTimeout, httpx.RemoteProtocolError),
        )
        if not (before_send or safe_read):
            raise
    await anyio.sleep(0.25)
    return await client.request(method, url, **kwargs)


@asynccontextmanager
async def provider_client(client: httpx.AsyncClient | None):
    if client is not None:
        yield client
    else:
        async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=False) as owned:
            yield owned


async def request_json(
    client: httpx.AsyncClient, method: str, url: str, **kwargs: Any,
) -> dict[str, Any]:
    try:
        async with client.stream(
            method, url, timeout=_TIMEOUT, follow_redirects=False, **kwargs,
        ) as response:
            if response.status_code != 200:
                raise OAuthUpstreamError("OAuth upstream request failed")
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > _MAX_RESPONSE_BYTES:
                    raise OAuthUpstreamError("OAuth upstream response exceeded size limit")
        payload = json.loads(body)
    except (httpx.HTTPError, TimeoutError) as exc:
        raise OAuthUpstreamError("OAuth upstream request failed") from exc
    except (ValueError, UnicodeDecodeError) as exc:
        raise OAuthUpstreamError("OAuth upstream returned invalid JSON") from exc
    if not isinstance(payload, dict) or "error" in payload:
        raise OAuthUpstreamError("OAuth upstream returned an error")
    return payload


def required_text(payload: dict[str, Any], key: str, *, max_length: int = 8192) -> str:
    value = payload.get(key)
    if (
        not isinstance(value, str) or not value or len(value) > max_length
        or any(ord(char) <= 32 or ord(char) == 127 for char in value)
    ):
        raise OAuthUpstreamError("OAuth response lacked required identity data")
    return value


def optional_text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""
