from __future__ import annotations

import httpx
import pytest

from backend.app.services.auth.oauth.providers._http import request_with_retry


@pytest.mark.anyio
@pytest.mark.parametrize("method", ["GET", "POST"])
@pytest.mark.parametrize("status", [302, 400, 401, 429, 500, 503])
async def test_http_responses_are_never_retried_or_followed(method, status):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status, headers={"location": "https://other.example/token"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False) as client:
        response = await request_with_retry(client, method, "https://oauth.example/token")
    assert response.status_code == status
    assert len(calls) == 1


@pytest.mark.anyio
async def test_retry_keeps_request_options_and_uses_only_one_backoff(monkeypatch):
    calls, sleeps = [], []

    async def sleep(delay):
        sleeps.append(delay)

    monkeypatch.setattr("backend.app.services.auth.oauth.providers._http.anyio.sleep", sleep)

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            raise httpx.ConnectError("network", request=request)
        return httpx.Response(200)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False) as client:
        await request_with_retry(client, "POST", "https://oauth.example/token", data={"code": "c", "code_verifier": "v"}, headers={"accept": "application/json"}, timeout=3)
    assert sleeps == [0.25]
    assert len(calls) == 2
    assert calls[0].content == calls[1].content == b"code=c&code_verifier=v"
    assert calls[0].headers == calls[1].headers
    assert calls[0].extensions == calls[1].extensions
