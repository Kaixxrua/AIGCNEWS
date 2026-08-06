from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import httpx
import pytest

from backend.app.services.wechat_sogou.errors import (
    SogouBlockedError,
    SogouUpstreamError,
)
from backend.app.services.wechat_sogou.transport import SogouWechatTransport

FIXTURES = Path(__file__).parent / "fixtures" / "wechat_sogou"


def _fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


class _FakeResponse:
    def __init__(
        self,
        content: bytes,
        *,
        status_code: int = 200,
        headers: list[tuple[str, str]] | None = None,
    ) -> None:
        self.status_code = status_code
        self.headers = httpx.Headers(headers or [])
        self._content = content

    async def aread(self) -> bytes:
        return self._content


def _make_transport(
    responses: list[_FakeResponse],
    captured: dict[str, Any],
) -> SogouWechatTransport:
    class FakeClient:
        def __init__(self, **kwargs) -> None:
            captured.setdefault("client_kwargs", kwargs)

        async def request(self, **kwargs) -> _FakeResponse:
            captured.setdefault("requests", []).append(kwargs)
            return responses.pop(0)

        async def aclose(self) -> None:
            pass

    return SogouWechatTransport(client_factory=FakeClient)


def test_search_articles_builds_fixed_query() -> None:
    captured: dict[str, Any] = {}
    transport = _make_transport([_FakeResponse(_fixture("search_page.html"))], captured)

    response = asyncio.run(transport.search_articles("AI迷思录", page=2))

    assert response.status_code == 200
    url = captured["requests"][0]["url"]
    assert "type=2" in url and "query=AI" in url and "page=2" in url
    client_headers = captured["client_kwargs"]["headers"]
    assert "Chrome" in client_headers.get("User-Agent", "")


def test_search_articles_raises_blocked_on_antispider_body() -> None:
    transport = _make_transport([_FakeResponse(b"<html>antispider</html>")], {})

    with pytest.raises(SogouBlockedError):
        asyncio.run(transport.search_articles("AI迷思录"))


def test_search_articles_raises_upstream_on_non_200() -> None:
    transport = _make_transport([_FakeResponse(b"", status_code=503)], {})

    with pytest.raises(SogouUpstreamError):
        asyncio.run(transport.search_articles("AI迷思录"))


def test_resolve_article_url_sends_jar_and_referer() -> None:
    captured: dict[str, Any] = {}
    responses = [
        _FakeResponse(
            _fixture("search_page.html"),
            headers=[("set-cookie", "SNUID=abc123; Path=/")],
        ),
        _FakeResponse(_fixture("redirect_page.html")),
    ]
    transport = _make_transport(responses, captured)

    async def _run() -> str:
        await transport.search_articles("AI迷思录")
        return await transport.resolve_article_url(
            "/link?url=xyz", referer="https://weixin.sogou.com/weixin?type=2"
        )

    url = asyncio.run(_run())

    assert url.startswith("https://mp.weixin.qq.com/s?src=11")
    resolve_headers = captured["requests"][1]["headers"]
    assert "SNUID=abc123" in resolve_headers.get("Cookie", "")
    assert resolve_headers.get("Referer") == "https://weixin.sogou.com/weixin?type=2"


def test_resolve_article_url_rejects_foreign_path() -> None:
    transport = _make_transport([], {})

    with pytest.raises(SogouUpstreamError):
        asyncio.run(
            transport.resolve_article_url(
                "/weixin?type=2", referer="https://weixin.sogou.com/"
            )
        )


def test_resolve_article_url_raises_blocked_on_antispider_redirect() -> None:
    responses = [
        _FakeResponse(
            b"",
            status_code=302,
            headers=[("location", "http://weixin.sogou.com/antispider/?from=%2Flink")],
        )
    ]
    transport = _make_transport(responses, {})

    with pytest.raises(SogouBlockedError):
        asyncio.run(
            transport.resolve_article_url(
                "/link?url=xyz", referer="https://weixin.sogou.com/"
            )
        )


def test_fetch_article_page_rejects_non_mp_url() -> None:
    transport = _make_transport([], {})

    with pytest.raises(SogouUpstreamError):
        asyncio.run(transport.fetch_article_page("https://evil.example.com/x"))
