from __future__ import annotations

from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
import yaml

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


def test_website_fetcher_ignores_ambient_proxy_when_fallback_is_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ALL_PROXY", "socks5h://198.51.100.1:1080")
    monkeypatch.setattr(tool_website_fetcher.settings, "outbound_proxy", "")
    fetch = Mock(side_effect=httpx.ConnectError("offline"))
    monkeypatch.setattr(tool_website_fetcher, "_fetch_tool_website_metadata", fetch)

    with pytest.raises(tool_website_fetcher.ToolWebsiteFetchError, match="无法连接目标网站"):
        tool_website_fetcher.fetch_tool_website_metadata("https://example.com")

    fetch.assert_called_once_with("https://example.com")


def test_website_fetcher_falls_back_to_configured_proxy_after_transport_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    metadata = Mock()
    monkeypatch.setattr(
        tool_website_fetcher.settings,
        "outbound_proxy",
        "socks5h://198.51.100.1:1080",
    )
    fetch = Mock(side_effect=[httpx.ConnectTimeout("offline"), metadata])
    monkeypatch.setattr(tool_website_fetcher, "_fetch_tool_website_metadata", fetch)

    assert tool_website_fetcher.fetch_tool_website_metadata("https://www.youtube.com") is metadata
    assert fetch.call_args_list == [
        (("https://www.youtube.com",), {}),
        (("https://www.youtube.com",), {"proxy_url": "socks5h://198.51.100.1:1080"}),
    ]


def test_website_fetcher_does_not_use_proxy_when_direct_fetch_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    metadata = Mock()
    monkeypatch.setattr(tool_website_fetcher.settings, "outbound_proxy", "http://proxy:7897")
    fetch = Mock(return_value=metadata)
    monkeypatch.setattr(tool_website_fetcher, "_fetch_tool_website_metadata", fetch)

    assert tool_website_fetcher.fetch_tool_website_metadata("https://example.com") is metadata
    fetch.assert_called_once_with("https://example.com")


def test_website_fetcher_does_not_proxy_policy_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tool_website_fetcher.settings, "outbound_proxy", "http://proxy:7897")
    fetch = Mock(side_effect=tool_website_fetcher.ToolWebsiteFetchError("网页内容过大"))
    monkeypatch.setattr(tool_website_fetcher, "_fetch_tool_website_metadata", fetch)

    with pytest.raises(tool_website_fetcher.ToolWebsiteFetchError, match="网页内容过大"):
        tool_website_fetcher.fetch_tool_website_metadata("https://example.com")

    fetch.assert_called_once_with("https://example.com")


def test_website_fetcher_sanitizes_proxy_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    proxy_url = "socks5h://user:secret@198.51.100.1:1080"
    monkeypatch.setattr(tool_website_fetcher.settings, "outbound_proxy", proxy_url)
    fetch = Mock(side_effect=[httpx.ConnectError("direct"), httpx.ConnectError(proxy_url)])
    monkeypatch.setattr(tool_website_fetcher, "_fetch_tool_website_metadata", fetch)

    with pytest.raises(tool_website_fetcher.ToolWebsiteFetchError) as exc_info:
        tool_website_fetcher.fetch_tool_website_metadata("https://example.com")

    assert str(exc_info.value) == "直接连接和出站代理均无法访问目标网站"
    assert "secret" not in str(exc_info.value)


def test_youtube_uses_remote_dns_only_with_socks5h() -> None:
    assert tool_website_fetcher._proxy_uses_remote_dns(
        "socks5h://198.51.100.1:1080", "www.youtube.com"
    )
    assert tool_website_fetcher._proxy_uses_remote_dns("socks5h://198.51.100.1:1080", "youtu.be")
    assert not tool_website_fetcher._proxy_uses_remote_dns(
        "socks5h://198.51.100.1:1080", "youtube.com.attacker.example"
    )
    assert not tool_website_fetcher._proxy_uses_remote_dns(
        "http://198.51.100.1:7897", "www.youtube.com"
    )


def test_proxy_request_is_pinned_to_validated_ip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        tool_website_fetcher,
        "_safe_resolved_ips",
        Mock(return_value=["8.8.8.8", "2001:4860:4860::8888"]),
    )

    request_url, headers, extensions = tool_website_fetcher._proxy_request_target(
        "https://www.youtube.com/watch?v=abc"
    )

    assert request_url == "https://8.8.8.8/watch?v=abc"
    assert headers == {"Host": "www.youtube.com"}
    assert extensions == {"sni_hostname": "www.youtube.com"}


def test_invalid_proxy_configuration_is_sanitized(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        tool_website_fetcher.settings,
        "outbound_proxy",
        "ftp://user:secret@proxy.example:21",
    )
    fetch = Mock(side_effect=httpx.ConnectError("direct"))
    monkeypatch.setattr(tool_website_fetcher, "_fetch_tool_website_metadata", fetch)

    with pytest.raises(tool_website_fetcher.ToolWebsiteFetchError) as exc_info:
        tool_website_fetcher.fetch_tool_website_metadata("https://example.com")

    assert str(exc_info.value) == "出站代理配置无效"
    assert "secret" not in str(exc_info.value)
    fetch.assert_called_once_with("https://example.com")


def test_httpx_accepts_socks5h_proxy_when_socks_extra_is_installed() -> None:
    try:
        transport = httpx.HTTPTransport(proxy="socks5h://198.51.100.1:1080")
    except ImportError as exc:  # pragma: no cover - documents the required extra
        pytest.fail(f"httpx SOCKS support is not installed: {exc}")
    transport.close()


def test_compose_routes_first_party_model_relay_and_internal_services_directly(monkeypatch):
    compose = yaml.safe_load((Path(__file__).resolve().parents[2] / 'docker/docker-compose.yml').read_text())
    checked = 0
    for service in compose['services'].values():
        environment = service.get('environment', [])
        if not isinstance(environment, list):
            continue
        for entry in environment:
            if not isinstance(entry, str) or not entry.startswith(('NO_PROXY=', 'no_proxy=')):
                continue
            _, bypass = entry.split('=', 1)
            monkeypatch.setenv('NO_PROXY', bypass)
            monkeypatch.setenv('no_proxy', bypass)
            monkeypatch.setenv('HTTPS_PROXY', 'http://127.0.0.1:7897')
            monkeypatch.setenv('https_proxy', 'http://127.0.0.1:7897')
            with httpx.Client(trust_env=True) as client:
                assert client._transport_for_url(httpx.URL('https://api.aigcnews.cn/v1')) is client._transport
                assert client._transport_for_url(httpx.URL('http://minio:9000')) is client._transport
                assert client._transport_for_url(httpx.URL('https://arxiv.org/abs/2610.12345')) is not client._transport
                assert client._transport_for_url(httpx.URL('https://api.aigcnews.cn.attacker.example')) is not client._transport
            checked += 1
    assert checked == 4
