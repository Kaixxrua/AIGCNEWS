from __future__ import annotations

"""X 已删推文 janitor 服务契约：分拣、fail-closed、cap、共享被引。

传输层四态口径见私有仓 tests/test_x_source_contracts.py 的
XExistenceProbe* 契约；这里只验证服务层对各态的处置与写入路径。
"""

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.app.services.source_plugins.x_source import (
    XAuthAbort,
    XAuthNotConfigured,
    XRateLimitAbort,
)
from backend.app.services.x_janitor.deleted_tweets import (
    XDeletedTweetJanitor,
    extract_author_handle,
    extract_quoted_author_handle,
    extract_quoted_tweet_id,
    extract_tweet_id,
)

_CACHE_PATCH = "backend.app.services.x_janitor.deleted_tweets.clear_dashboard_cache_safely"
_LOADER_PATCH = "backend.app.services.x_janitor.deleted_tweets.load_x_transport_class"


def _doc(doc_id: str, tweet_id: str, quoted_id: str | None = None) -> dict:
    quote = None
    if quoted_id is not None:
        quote = {"url": f"https://x.com/other/status/{quoted_id}", "text": "quoted"}
    return {
        "id": doc_id,
        "url": f"https://x.com/author/status/{tweet_id}",
        "quote": quote,
    }


def _janitor(
    rows: list[dict],
    statuses: dict[str, str] | Exception,
    *,
    max_probes: int = 150,
    transport: object | None = None,
):
    documents = MagicMock()
    documents.list_x_documents_for_probe.return_value = rows
    documents.delete_documents.side_effect = lambda ids: list(ids)
    documents.clear_quotes_for_docs.side_effect = lambda ids: list(ids)
    x_credentials = MagicMock()
    if isinstance(statuses, Exception):
        probe = MagicMock(side_effect=statuses)
    else:
        probe = MagicMock(return_value=statuses)
    if transport is None:
        transport = MagicMock()
        transport.probe_tweet_existence = probe
    janitor = XDeletedTweetJanitor(
        documents,
        x_credentials,
        transport=transport,
        max_probes_per_run=max_probes,
    )
    return janitor, documents, transport


class ExtractTweetIdContracts(unittest.TestCase):
    def test_extracts_status_id(self) -> None:
        self.assertEqual(
            extract_tweet_id("https://x.com/openai/status/1990123456789"), "1990123456789"
        )
        self.assertEqual(
            extract_tweet_id("https://twitter.com/a/status/42?s=20"), "42"
        )

    def test_non_status_url_and_empty_input_return_empty(self) -> None:
        for url in ("", None, "https://x.com/openai", "https://example.com/status/"):
            with self.subTest(url=url):
                self.assertEqual(extract_tweet_id(url), "")

    def test_extract_quoted_tweet_id_reads_quote_url(self) -> None:
        self.assertEqual(
            extract_quoted_tweet_id({"url": "https://x.com/b/status/77"}), "77"
        )
        for quote in (None, "not-a-dict", {}, {"url": None}):
            with self.subTest(quote=quote):
                self.assertEqual(extract_quoted_tweet_id(quote), "")

    def test_extract_author_handle(self) -> None:
        self.assertEqual(
            extract_author_handle("https://x.com/OpenAI/status/123"), "OpenAI"
        )
        self.assertEqual(
            extract_author_handle("https://twitter.com/someone/status/9?s=20"), "someone"
        )
        for url in ("", None, "https://example.com/a/status/1", "https://x.com/openai"):
            with self.subTest(url=url):
                self.assertEqual(extract_author_handle(url), "")

    def test_extract_quoted_author_handle_prefers_author_field(self) -> None:
        self.assertEqual(
            extract_quoted_author_handle(
                {"url": "https://x.com/b/status/77", "author": "@Quoted"}
            ),
            "Quoted",
        )
        self.assertEqual(
            extract_quoted_author_handle({"url": "https://x.com/b/status/77"}), "b"
        )
        for quote in (None, "not-a-dict", {}):
            with self.subTest(quote=quote):
                self.assertEqual(extract_quoted_author_handle(quote), "")


class XDeletedTweetJanitorContracts(unittest.IsolatedAsyncioTestCase):
    async def test_own_deleted_deletes_document_and_clears_cache(self) -> None:
        janitor, documents, _ = _janitor(
            [_doc("d1", "1001"), _doc("d2", "1002")],
            {"1001": "deleted", "1002": "alive"},
        )
        with patch(_CACHE_PATCH, new=AsyncMock()) as clear_cache:
            report = await janitor.run()

        documents.delete_documents.assert_called_once_with(["d1"])
        documents.clear_quotes_for_docs.assert_not_called()
        clear_cache.assert_awaited_once()
        self.assertEqual(report.deleted_doc_ids, ["d1"])
        self.assertEqual(report.cleared_quote_doc_ids, [])
        self.assertIsNone(report.aborted)
        self.assertEqual((report.probed, report.deleted, report.alive), (2, 1, 1))

    async def test_quoted_deleted_clears_quote_card_only(self) -> None:
        janitor, documents, _ = _janitor(
            [_doc("d1", "1001", quoted_id="2001")],
            {"1001": "alive", "2001": "deleted"},
        )
        with patch(_CACHE_PATCH, new=AsyncMock()) as clear_cache:
            report = await janitor.run()

        documents.delete_documents.assert_not_called()
        documents.clear_quotes_for_docs.assert_called_once_with(["d1"])
        clear_cache.assert_awaited_once()
        self.assertEqual(report.cleared_quote_doc_ids, ["d1"])
        self.assertEqual(report.deleted_doc_ids, [])

    async def test_own_and_quoted_both_deleted_deletes_document_without_clear(self) -> None:
        """外推已删时整文删除，引用卡随之消失，不再单独清卡。"""
        janitor, documents, _ = _janitor(
            [_doc("d1", "1001", quoted_id="2001")],
            {"1001": "deleted", "2001": "deleted"},
        )
        with patch(_CACHE_PATCH, new=AsyncMock()):
            report = await janitor.run()

        documents.delete_documents.assert_called_once_with(["d1"])
        documents.clear_quotes_for_docs.assert_not_called()
        self.assertEqual(report.deleted_doc_ids, ["d1"])
        self.assertEqual(report.cleared_quote_doc_ids, [])

    async def test_unavailable_and_unknown_write_nothing(self) -> None:
        janitor, documents, _ = _janitor(
            [_doc("d1", "1001"), _doc("d2", "1002", quoted_id="2001")],
            {"1001": "unavailable", "1002": "alive", "2001": "unknown"},
        )
        with patch(_CACHE_PATCH, new=AsyncMock()) as clear_cache:
            report = await janitor.run()

        documents.delete_documents.assert_not_called()
        documents.clear_quotes_for_docs.assert_not_called()
        clear_cache.assert_not_awaited()
        self.assertEqual((report.unavailable, report.unknown), (1, 1))
        self.assertEqual(report.deleted_doc_ids, [])
        self.assertEqual(report.cleared_quote_doc_ids, [])

    async def test_shared_quoted_tweet_probed_once_and_clears_all_outers(self) -> None:
        janitor, documents, transport = _janitor(
            [_doc("d1", "1001", quoted_id="2001"), _doc("d2", "1002", quoted_id="2001")],
            {"1001": "alive", "1002": "alive", "2001": "deleted"},
        )
        with patch(_CACHE_PATCH, new=AsyncMock()):
            report = await janitor.run()

        probed_ids = transport.probe_tweet_existence.call_args.args[0]
        self.assertEqual(probed_ids.count("2001"), 1)
        documents.clear_quotes_for_docs.assert_called_once_with(["d1", "d2"])
        self.assertEqual(report.cleared_quote_doc_ids, ["d1", "d2"])

    async def test_malformed_quote_probes_own_only(self) -> None:
        rows = [
            {"id": "d1", "url": "https://x.com/a/status/1001", "quote": "{bad json"},
            {"id": "d2", "url": "not-a-tweet-url", "quote": None},
        ]
        janitor, _, transport = _janitor(rows, {"1001": "alive"})
        with patch(_CACHE_PATCH, new=AsyncMock()):
            await janitor.run()

        probed_ids = transport.probe_tweet_existence.call_args.args[0]
        self.assertEqual(probed_ids, ["1001"])

    async def test_cap_truncates_probe_list(self) -> None:
        rows = [
            _doc("d1", "1001", quoted_id="2001"),
            _doc("d2", "1002"),
            _doc("d3", "1003"),
        ]
        janitor, _, transport = _janitor(
            rows, {"1001": "alive", "2001": "alive"}, max_probes=2
        )
        with patch(_CACHE_PATCH, new=AsyncMock()):
            report = await janitor.run()

        probed_ids = transport.probe_tweet_existence.call_args.args[0]
        self.assertEqual(probed_ids, ["1001", "2001"])
        self.assertEqual(report.probed, 2)

    async def test_rate_limit_aborts_with_zero_writes(self) -> None:
        janitor, documents, _ = _janitor(
            [_doc("d1", "1001")], XRateLimitAbort("x_rate_limited")
        )
        with patch(_CACHE_PATCH, new=AsyncMock()) as clear_cache:
            report = await janitor.run()

        self.assertEqual(report.aborted, "x_rate_limited")
        documents.delete_documents.assert_not_called()
        documents.clear_quotes_for_docs.assert_not_called()
        clear_cache.assert_not_awaited()

    async def test_auth_failures_abort_with_zero_writes(self) -> None:
        for exc, reason in (
            (XAuthAbort("x_auth_expired"), "x_auth_expired"),
            (XAuthNotConfigured("x_auth_not_configured"), "x_auth_not_configured"),
        ):
            with self.subTest(reason=reason):
                janitor, documents, _ = _janitor([_doc("d1", "1001")], exc)
                with patch(_CACHE_PATCH, new=AsyncMock()):
                    report = await janitor.run()
                self.assertEqual(report.aborted, reason)
                documents.delete_documents.assert_not_called()
                documents.clear_quotes_for_docs.assert_not_called()

    async def test_transport_missing_probe_method_aborts(self) -> None:
        class LegacyTransport:
            pass

        janitor, documents, _ = _janitor(
            [_doc("d1", "1001")], {}, transport=LegacyTransport()
        )
        with patch(_CACHE_PATCH, new=AsyncMock()):
            report = await janitor.run()

        self.assertEqual(report.aborted, "transport_missing_probe")
        documents.delete_documents.assert_not_called()

    async def test_loader_none_aborts_transport_unavailable(self) -> None:
        documents = MagicMock()
        documents.list_x_documents_for_probe.return_value = [_doc("d1", "1001")]
        janitor = XDeletedTweetJanitor(documents, MagicMock())  # 无注入 transport
        with patch(_LOADER_PATCH, return_value=None), patch(
            _CACHE_PATCH, new=AsyncMock()
        ):
            report = await janitor.run()

        self.assertEqual(report.aborted, "x_transport_unavailable")
        documents.delete_documents.assert_not_called()

    async def test_loader_path_constructs_transport_with_credential_provider(self) -> None:
        documents = MagicMock()
        documents.list_x_documents_for_probe.return_value = [_doc("d1", "1001")]
        x_credentials = MagicMock()
        transport = MagicMock()
        transport.probe_tweet_existence.return_value = {"1001": "alive"}
        transport_class = MagicMock(return_value=transport)
        janitor = XDeletedTweetJanitor(documents, x_credentials)
        with patch(_LOADER_PATCH, return_value=transport_class), patch(
            _CACHE_PATCH, new=AsyncMock()
        ):
            report = await janitor.run()

        transport_class.assert_called_once_with(
            credential_provider=x_credentials.list_enabled_x_credentials
        )
        self.assertIsNone(report.aborted)
        self.assertEqual(report.probed, 1)

    async def test_no_x_documents_short_circuits(self) -> None:
        janitor, documents, transport = _janitor([], {})
        with patch(_CACHE_PATCH, new=AsyncMock()) as clear_cache:
            report = await janitor.run()

        transport.probe_tweet_existence.assert_not_called()
        documents.delete_documents.assert_not_called()
        clear_cache.assert_not_awaited()
        self.assertEqual(report.probed, 0)
        self.assertIsNone(report.aborted)

    async def test_probe_receives_author_handles_for_cross_check(self) -> None:
        """authors 映射：own 取自文档 URL，被引取自 quote.author（供空形态交叉验证）。"""
        janitor, _, transport = _janitor(
            [
                _doc("d1", "1001", quoted_id="2001"),
                {"id": "d2", "url": "https://x.com/Second/status/1002", "quote": None},
            ],
            {"1001": "alive", "2001": "alive", "1002": "alive"},
        )
        with patch(_CACHE_PATCH, new=AsyncMock()):
            await janitor.run()

        call = transport.probe_tweet_existence.call_args
        self.assertEqual(call.args[0], ["1001", "2001", "1002"])
        self.assertEqual(
            call.args[1],
            {"1001": "author", "2001": "other", "1002": "Second"},
        )


if __name__ == "__main__":
    unittest.main()
