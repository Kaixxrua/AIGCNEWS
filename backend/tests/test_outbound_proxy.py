from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest

from backend.app.services.ingestion import source_news, tool_website_fetcher


def test_rss_is_downloaded_with_httpx_before_parsing(monkeypatch: pytest.MonkeyPatch) -> None:
    response = Mock()
    response.content = b"<rss><channel></channel></rss>"
    response.raise_for_status.return_value = None
    client = Mock()
    client.__enter__ = Mock(return_value=client)
    client.__exit__ = Mock(return_value=False)
    client.get.return_value = response

    parsed = SimpleNamespace(entries=[])
    parse = Mock(return_value=parsed)
    monkeypatch.setattr(httpx, "Client", Mock(return_value=client))
    monkeypatch.setitem(__import__("sys").modules, "feedparser", SimpleNamespace(parse=parse))

    assert source_news._fetch_rss_articles(10, "daily", date.today(), "tech") == []
    client.get.assert_called_once_with(source_news.TECHMEME_RSS_URL)
    response.raise_for_status.assert_called_once_with()
    parse.assert_called_once_with(response.content)


def test_rss_network_failure_does_not_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    client = Mock()
    client.__enter__ = Mock(return_value=client)
    client.__exit__ = Mock(return_value=False)
    client.get.side_effect = httpx.ConnectError("offline")
    monkeypatch.setattr(httpx, "Client", Mock(return_value=client))
    monkeypatch.setitem(__import__("sys").modules, "feedparser", SimpleNamespace(parse=Mock()))

    assert source_news._fetch_rss_articles(10, "daily", date.today(), "tech") == []
    client.get.assert_called_once_with(source_news.TECHMEME_RSS_URL)


def test_website_fetcher_never_falls_back_to_environment_proxy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ALL_PROXY", "socks5h://10.20.0.1:1080")
    fetch = Mock(side_effect=httpx.ConnectError("offline"))
    monkeypatch.setattr(tool_website_fetcher, "_fetch_tool_website_metadata", fetch)

    with pytest.raises(tool_website_fetcher.ToolWebsiteFetchError, match="无法连接目标网站"):
        tool_website_fetcher.fetch_tool_website_metadata("https://example.com")

    fetch.assert_called_once_with("https://example.com", trust_env=False)


def test_httpx_accepts_socks5h_proxy_when_socks_extra_is_installed() -> None:
    try:
        transport = httpx.HTTPTransport(proxy="socks5h://10.20.0.1:1080")
    except ImportError as exc:  # pragma: no cover - documents the required extra
        pytest.fail(f"httpx SOCKS support is not installed: {exc}")
    transport.close()
