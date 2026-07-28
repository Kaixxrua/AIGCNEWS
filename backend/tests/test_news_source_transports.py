from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock

from backend.app.services.ingestion.sources.hackernews_transport import (
    HN_ITEM_URL,
    HN_TOP_STORIES_URL,
    HackerNewsTransport,
)
from backend.app.services.ingestion.sources.news_transport import (
    TECHMEME_HOME_URL,
    TECHMEME_RSS_URL,
    TechmemeTransport,
)


class NewsTransportTests(unittest.TestCase):
    def test_techmeme_transport_preserves_exact_clients_and_returns_raw_data(self) -> None:
        rss_client = MagicMock()
        rss_client.__enter__.return_value = rss_client
        rss_client.__exit__.return_value = None
        rss_client.get.return_value.content = b"rss-bytes"
        home_client = MagicMock()
        home_client.__enter__.return_value = home_client
        home_client.__exit__.return_value = None
        home_client.get.return_value.text = "homepage-text"
        factory = MagicMock(side_effect=[rss_client, home_client])
        transport = TechmemeTransport(factory)

        self.assertEqual(transport.fetch_rss(), b"rss-bytes")
        self.assertEqual(transport.fetch_homepage(), "homepage-text")

        self.assertEqual(factory.call_count, 2)
        for call in factory.call_args_list:
            self.assertEqual(call.kwargs["timeout"], 20)
            self.assertTrue(call.kwargs["follow_redirects"])
        self.assertNotIn("Accept", factory.call_args_list[0].kwargs["headers"])
        self.assertIn("Accept", factory.call_args_list[1].kwargs["headers"])
        rss_client.get.assert_called_once_with(TECHMEME_RSS_URL)
        home_client.get.assert_called_once_with(TECHMEME_HOME_URL)
        rss_client.get.return_value.raise_for_status.assert_called_once_with()
        home_client.get.return_value.raise_for_status.assert_called_once_with()


class _AsyncClient:
    def __init__(self, responses) -> None:
        self.get = AsyncMock(side_effect=responses)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        return None


class _Response:
    def __init__(self, value) -> None:
        self._value = value

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return self._value


class HackerNewsTransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_hn_transport_preserves_two_clients_top_cap_and_item_timeout(self) -> None:
        top_client = _AsyncClient([_Response(list(range(40)))])
        item_client = _AsyncClient([_Response({"id": index}) for index in range(30)])
        factory = MagicMock(side_effect=[top_client, item_client])
        transport = HackerNewsTransport(factory)

        top_ids = await transport.fetch_top_ids()
        items = await transport.fetch_items(top_ids)

        self.assertEqual(top_ids, list(range(30)))
        self.assertEqual(len(items), 30)
        self.assertEqual(
            factory.call_args_list[0].kwargs,
            {"timeout": 15, "trust_env": True, "follow_redirects": True},
        )
        self.assertEqual(
            factory.call_args_list[1].kwargs,
            {"timeout": 10, "trust_env": True, "follow_redirects": True},
        )
        top_client.get.assert_awaited_once_with(HN_TOP_STORIES_URL)
        item_client.get.assert_any_await(
            HN_ITEM_URL.format(item_id=0),
            timeout=10,
        )

    async def test_hn_item_failure_is_returned_as_partial_none(self) -> None:
        item_client = _AsyncClient([RuntimeError("offline"), _Response({"id": 2})])
        transport = HackerNewsTransport(MagicMock(return_value=item_client))

        results = await transport.fetch_items([1, 2])

        self.assertEqual(results, [None, {"id": 2}])


if __name__ == "__main__":
    unittest.main()
