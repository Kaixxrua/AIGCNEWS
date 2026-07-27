from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from backend.app.services.ingestion import content_enricher, content_fetch_port


class _AsyncClient:
    def __init__(self, response: object = None, error: Exception | None = None, **kwargs: object):
        self.response = response
        self.error = error
        self.kwargs = kwargs
        self.requested_urls: list[str] = []

    async def __aenter__(self) -> _AsyncClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def get(self, url: str) -> object:
        self.requested_urls.append(url)
        if self.error is not None:
            raise self.error
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
                response.headers = {"content-type": content_type}
                response.text = "<p>body</p>"
                client = _AsyncClient(response=response)
                with patch.object(
                    content_fetch_port.httpx,
                    "AsyncClient",
                    return_value=client,
                ) as factory:
                    self.assertEqual(
                        await fetcher.fetch("https://example.test/page", timeout=7),
                        "cleaned",
                    )

                factory.assert_called_once_with(
                    timeout=7,
                    follow_redirects=True,
                    headers={"User-Agent": "contract"},
                    trust_env=True,
                )
                response.raise_for_status.assert_called_once_with()
                cleaner.assert_called_with("<p>body</p>")

    async def test_rejects_other_content_types_and_returns_empty_on_failure(self) -> None:
        fetcher = content_fetch_port.DefaultPageContentFetcher()
        response = MagicMock()
        response.headers = {"content-type": "application/json"}
        response.text = "ignored"
        with patch.object(
            content_fetch_port.httpx,
            "AsyncClient",
            return_value=_AsyncClient(response=response),
        ):
            self.assertEqual(await fetcher.fetch("http://example.test/data"), "")

        for error in (httpx.HTTPError("network"), RuntimeError("client")):
            with self.subTest(error=type(error).__name__):
                with patch.object(
                    content_fetch_port.httpx,
                    "AsyncClient",
                    return_value=_AsyncClient(error=error),
                ):
                    self.assertEqual(await fetcher.fetch("http://example.test/error"), "")


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
