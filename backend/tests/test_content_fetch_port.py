from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from backend.app.services.ingestion import content_enricher, content_fetch_port
from backend.app.services.outbound_target_policy import (
    OutboundTargetPolicyError,
    PinnedHttpTarget,
)


def _pinned_target(url: str) -> PinnedHttpTarget:
    return PinnedHttpTarget(
        logical_url=url,
        request_url=url,
        host_header="example.test",
        sni_hostname="example.test",
        selected_ip="93.184.216.34",
    )


class _AsyncClient:
    def __init__(self, response: object = None, error: Exception | None = None, **kwargs: object):
        self.response = response
        self.error = error
        self.kwargs = kwargs
        self.requested_urls: list[str] = []
        self.request_kwargs: list[dict[str, object]] = []

    async def __aenter__(self) -> _AsyncClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def get(self, url: str, **kwargs: object) -> object:
        self.requested_urls.append(url)
        self.request_kwargs.append(kwargs)
        if self.error is not None:
            raise self.error
        if isinstance(self.response, list):
            return self.response.pop(0)
        return self.response


class _SyncClient:
    def __init__(self, **kwargs: object):
        self.kwargs = kwargs
        self.entered = False

    def __enter__(self) -> _SyncClient:
        self.entered = True
        return self

    def __exit__(self, *args: object) -> None:
        return None


class ContentFetchPortProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_protocol_shapes_accept_injected_fetchers(self) -> None:
        page: content_fetch_port.PageContentFetcher = content_fetch_port.DefaultPageContentFetcher()
        readme: content_fetch_port.GitHubReadmeFetcher = (
            content_fetch_port.DefaultGitHubReadmeFetcher()
        )

        with (
            patch.object(content_fetch_port.httpx, "AsyncClient") as async_client,
            patch.object(content_fetch_port.httpx, "Client") as sync_client,
        ):
            self.assertEqual(await page.fetch(""), "")
            self.assertEqual(await readme.fetch("invalid"), "")
        async_client.assert_not_called()
        sync_client.assert_not_called()


class DefaultPageContentFetcherTests(unittest.IsolatedAsyncioTestCase):
    async def test_preserves_url_gate_options_content_types_and_cleaner_injection(self) -> None:
        cleaner = MagicMock(return_value="cleaned")
        fetcher = content_fetch_port.DefaultPageContentFetcher(
            headers={"User-Agent": "contract"},
            clean_html=cleaner,
        )

        with patch.object(content_fetch_port.httpx, "AsyncClient") as factory:
            self.assertEqual(await fetcher.fetch("ftp://example.test"), "")
        factory.assert_not_called()

        for content_type in ("text/html; charset=utf-8", "text/plain"):
            with self.subTest(content_type=content_type):
                response = MagicMock()
                response.status_code = 200
                response.headers = {"content-type": content_type}
                response.text = "<p>body</p>"
                client = _AsyncClient(response=response)
                with (
                    patch.object(
                        content_fetch_port.httpx,
                        "AsyncClient",
                        return_value=client,
                    ) as factory,
                    patch.object(
                        content_fetch_port,
                        "pin_http_target",
                        side_effect=lambda url, **kwargs: _pinned_target(url),
                    ) as pin,
                ):
                    self.assertEqual(
                        await fetcher.fetch("https://example.test/page", timeout=7),
                        "cleaned",
                    )

                factory.assert_called_once_with(
                    timeout=7,
                    follow_redirects=False,
                    headers={"User-Agent": "contract"},
                    trust_env=True,
                )
                pin.assert_called_once_with(
                    "https://example.test/page", allowed_ports={80, 443}
                )
                self.assertEqual(client.requested_urls, ["https://example.test/page"])
                self.assertEqual(
                    client.request_kwargs,
                    [
                        {
                            "headers": {"Host": "example.test"},
                            "extensions": {"sni_hostname": "example.test"},
                        }
                    ],
                )
                response.raise_for_status.assert_called_once_with()
                cleaner.assert_called_with("<p>body</p>")

    async def test_rejects_other_content_types_and_returns_empty_on_failure(self) -> None:
        fetcher = content_fetch_port.DefaultPageContentFetcher()
        response = MagicMock()
        response.status_code = 200
        response.headers = {"content-type": "application/json"}
        response.text = "ignored"
        with (
            patch.object(
                content_fetch_port.httpx,
                "AsyncClient",
                return_value=_AsyncClient(response=response),
            ),
            patch.object(
                content_fetch_port,
                "pin_http_target",
                side_effect=lambda url, **kwargs: _pinned_target(url),
            ),
        ):
            self.assertEqual(await fetcher.fetch("http://example.test/data"), "")

        for error in (httpx.HTTPError("network"), RuntimeError("client")):
            with self.subTest(error=type(error).__name__):
                with (
                    patch.object(
                        content_fetch_port.httpx,
                        "AsyncClient",
                        return_value=_AsyncClient(error=error),
                    ),
                    patch.object(
                        content_fetch_port,
                        "pin_http_target",
                        side_effect=lambda url, **kwargs: _pinned_target(url),
                    ),
                ):
                    self.assertEqual(await fetcher.fetch("http://example.test/error"), "")


class PageFetcherSsrfGuardTests(unittest.IsolatedAsyncioTestCase):
    async def test_denied_targets_are_rejected_before_any_http_request(self) -> None:
        # 走真实出站策略（不 patch pin）：云元数据/内网/回环地址与非标准
        # 端口必须在发出任何 HTTP 请求前被拒绝（渗透实测 SSRF 路径）。
        fetcher = content_fetch_port.DefaultPageContentFetcher()
        for url in (
            "http://169.254.169.254/latest/meta-data",
            "http://192.168.1.1/admin",
            "http://127.0.0.1/api",
            "http://example.test:8443/internal",
            "http://user:secret@example.test/page",
        ):
            with self.subTest(url=url):
                client = _AsyncClient(response=MagicMock())
                with patch.object(
                    content_fetch_port.httpx, "AsyncClient", return_value=client
                ):
                    self.assertEqual(await fetcher.fetch(url), "")
                self.assertEqual(client.requested_urls, [])

    async def test_redirects_are_followed_with_per_hop_pinning(self) -> None:
        cleaner = MagicMock(return_value="cleaned")
        fetcher = content_fetch_port.DefaultPageContentFetcher(clean_html=cleaner)
        first = MagicMock()
        first.status_code = 302
        first.headers = {"location": "/landing"}
        second = MagicMock()
        second.status_code = 200
        second.headers = {"content-type": "text/html"}
        second.text = "<p>final</p>"
        client = _AsyncClient(response=[first, second])
        pinned_urls: list[str] = []

        def fake_pin(url: str, **kwargs: object) -> PinnedHttpTarget:
            pinned_urls.append(url)
            return _pinned_target(url)

        with (
            patch.object(content_fetch_port.httpx, "AsyncClient", return_value=client),
            patch.object(content_fetch_port, "pin_http_target", side_effect=fake_pin),
        ):
            self.assertEqual(await fetcher.fetch("https://example.test/start"), "cleaned")

        # 每一跳都重新走策略钉死，相对 Location 基于当前逻辑 URL 解析
        self.assertEqual(
            pinned_urls,
            ["https://example.test/start", "https://example.test/landing"],
        )
        self.assertEqual(len(client.requested_urls), 2)
        cleaner.assert_called_once_with("<p>final</p>")

    async def test_redirect_to_denied_target_returns_empty(self) -> None:
        fetcher = content_fetch_port.DefaultPageContentFetcher()
        first = MagicMock()
        first.status_code = 302
        first.headers = {"location": "http://169.254.169.254/latest/meta-data"}
        client = _AsyncClient(response=first)

        def fake_pin(url: str, **kwargs: object) -> PinnedHttpTarget:
            if "169.254.169.254" in url:
                raise OutboundTargetPolicyError("不允许访问本地、内网或保留地址")
            return _pinned_target(url)

        with (
            patch.object(content_fetch_port.httpx, "AsyncClient", return_value=client),
            patch.object(content_fetch_port, "pin_http_target", side_effect=fake_pin),
        ):
            self.assertEqual(await fetcher.fetch("https://example.test/start"), "")
        # 只发出了第一跳请求，重定向目标在请求前已被拦截
        self.assertEqual(len(client.requested_urls), 1)

    async def test_redirect_loop_and_missing_location_return_empty(self) -> None:
        fetcher = content_fetch_port.DefaultPageContentFetcher()
        loop = MagicMock()
        loop.status_code = 302
        loop.headers = {"location": "/again"}
        client = _AsyncClient(response=loop)
        with (
            patch.object(content_fetch_port.httpx, "AsyncClient", return_value=client),
            patch.object(
                content_fetch_port,
                "pin_http_target",
                side_effect=lambda url, **kwargs: _pinned_target(url),
            ),
        ):
            self.assertEqual(await fetcher.fetch("https://example.test/loop"), "")
        # 5 跳上限 + 首次请求 = 6 次后放弃
        self.assertEqual(len(client.requested_urls), 6)

        missing = MagicMock()
        missing.status_code = 302
        missing.headers = {}
        client = _AsyncClient(response=missing)
        with (
            patch.object(content_fetch_port.httpx, "AsyncClient", return_value=client),
            patch.object(
                content_fetch_port,
                "pin_http_target",
                side_effect=lambda url, **kwargs: _pinned_target(url),
            ),
        ):
            self.assertEqual(await fetcher.fetch("https://example.test/loop"), "")
        self.assertEqual(len(client.requested_urls), 1)


class DefaultGitHubReadmeFetcherTests(unittest.IsolatedAsyncioTestCase):
    async def test_lazily_looks_up_snapshot_and_preserves_client_options(self) -> None:
        clients: list[_SyncClient] = []

        def client_factory(**kwargs: object) -> _SyncClient:
            client = _SyncClient(**kwargs)
            clients.append(client)
            return client

        snapshot_fetch = MagicMock(
            return_value=types.SimpleNamespace(status="succeeded", text="README")
        )
        source_stub = types.ModuleType("backend.app.services.ingestion.source_github")
        source_stub.fetch_github_readme_snapshot = snapshot_fetch

        fetcher = content_fetch_port.DefaultGitHubReadmeFetcher()
        with (
            patch.dict(sys.modules, {source_stub.__name__: source_stub}),
            patch.object(content_fetch_port.httpx, "Client", side_effect=client_factory),
            patch.object(content_fetch_port.asyncio, "to_thread", side_effect=lambda fn: fn()),
        ):
            self.assertEqual(await fetcher.fetch("owner/repo"), "README")

        self.assertEqual(
            clients[0].kwargs,
            {"timeout": 15, "follow_redirects": True, "trust_env": True},
        )
        self.assertTrue(clients[0].entered)
        snapshot_fetch.assert_called_once_with("owner/repo", clients[0], max_chars=20_000)

    async def test_non_success_and_exceptions_return_empty(self) -> None:
        for status in ("failed", "not_found", "rate_limited", "not_modified"):
            with self.subTest(status=status):
                source_stub = types.ModuleType("backend.app.services.ingestion.source_github")
                source_stub.fetch_github_readme_snapshot = MagicMock(
                    return_value=types.SimpleNamespace(status=status, text="ignored")
                )
                with (
                    patch.dict(sys.modules, {source_stub.__name__: source_stub}),
                    patch.object(content_fetch_port.httpx, "Client", _SyncClient),
                    patch.object(
                        content_fetch_port.asyncio,
                        "to_thread",
                        side_effect=lambda fn: fn(),
                    ),
                ):
                    self.assertEqual(
                        await content_fetch_port.DefaultGitHubReadmeFetcher().fetch(
                            "owner/repo"
                        ),
                        "",
                    )

        with patch.object(content_fetch_port.asyncio, "to_thread", side_effect=RuntimeError):
            self.assertEqual(
                await content_fetch_port.DefaultGitHubReadmeFetcher().fetch("owner/repo"),
                "",
            )


class ContentEnricherCompatibilityWrapperTests(unittest.IsolatedAsyncioTestCase):
    def test_clean_html_wrapper_forwards(self) -> None:
        with patch.object(content_enricher, "clean_html_text", return_value="clean") as clean:
            self.assertEqual(content_enricher._clean_html_text("html"), "clean")
        clean.assert_called_once_with("html")

    async def test_page_wrapper_forwards_with_legacy_headers_and_cleaner_seam(self) -> None:
        fetch = AsyncMock(return_value="page")
        adapter = MagicMock()
        adapter.fetch = fetch
        with patch.object(
            content_enricher,
            "DefaultPageContentFetcher",
            return_value=adapter,
        ) as factory:
            self.assertEqual(
                await content_enricher._fetch_url_text("http://example.test", timeout=3),
                "page",
            )

        factory.assert_called_once_with(
            headers=content_enricher._HEADERS,
            clean_html=content_enricher._clean_html_text,
        )
        fetch.assert_awaited_once_with("http://example.test", 3)

    async def test_readme_wrapper_forwards(self) -> None:
        fetch = AsyncMock(return_value="README")
        adapter = MagicMock()
        adapter.fetch = fetch
        with patch.object(
            content_enricher,
            "DefaultGitHubReadmeFetcher",
            return_value=adapter,
        ) as factory:
            self.assertEqual(
                await content_enricher._fetch_github_readme("owner/repo"),
                "README",
            )

        factory.assert_called_once_with()
        fetch.assert_awaited_once_with("owner/repo")


if __name__ == "__main__":
    unittest.main()
