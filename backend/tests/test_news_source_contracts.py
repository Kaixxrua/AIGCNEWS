from __future__ import annotations

import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from backend.app.services.ingestion import source_news
from backend.app.services.ingestion.crawlers import news_crawler


class _HttpResponse:
    def __init__(self, *, content: bytes = b"", text: str = "") -> None:
        self.content = content
        self.text = text

    def raise_for_status(self) -> None:
        return None


class TechmemeSourceContracts(unittest.TestCase):
    def test_rss_request_cap_filter_and_projection_contract(self) -> None:
        entries = []
        for index in range(17):
            entries.append(
                {
                    "title": f" Story {index} ",
                    "summary": f"<b>Summary</b> &amp; {index}",
                    "link": f"https://example.test/{index}",
                    "published": "Mon, 28 Jul 2026 12:00:00 GMT",
                }
            )
        fake_feedparser = SimpleNamespace(
            parse=MagicMock(return_value=SimpleNamespace(entries=entries))
        )
        client = MagicMock()
        client.__enter__.return_value = client
        client.__exit__.return_value = None
        client.get.return_value = _HttpResponse(content=b"synthetic-rss")

        with (
            patch.dict("sys.modules", {"feedparser": fake_feedparser}),
            patch("httpx.Client", return_value=client) as client_type,
        ):
            results = source_news._fetch_rss_articles(
                limit=30,
                period="daily",
                anchor=date(2026, 7, 28),
                source_channel="techmeme_daily_rss",
            )

        self.assertEqual(len(results), 15)
        client_type.assert_called_once()
        kwargs = client_type.call_args.kwargs
        self.assertEqual(kwargs["timeout"], 20)
        self.assertTrue(kwargs["follow_redirects"])
        self.assertIn("Mozilla/5.0", kwargs["headers"]["User-Agent"])
        client.get.assert_called_once_with(source_news.TECHMEME_RSS_URL)
        fake_feedparser.parse.assert_called_once_with(b"synthetic-rss")
        self.assertEqual(
            results[0],
            {
                "title": "Story 0",
                "abstract": "Summary & 0",
                "summary": "Summary & 0",
                "url": "https://example.test/0",
                "pdf_url": "",
                "source": "news",
                "source_channel": "techmeme_daily_rss",
                "channel": "techmeme_daily_rss",
                "score": 2.0,
                "raw_score": 2.0,
                "rank_in_period": 1,
                "tags": ["Techmeme", "daily"],
                "published_date": "2026-07-28",
                "feed_name": "Techmeme",
            },
        )

    def test_homepage_fills_after_rss_dedupes_and_excludes_internal_links(self) -> None:
        padding = " " * 1000
        html = padding + """
        <a class="ourHed" href="https://rss.test/item">Duplicate</a>
        <a class="ourHed" href="https://www.techmeme.com/inside">Internal</a>
        <a class="ourHed" href="https://external.test/one"><b>External One</b></a>
        <strong><a href="https://external.test/two">External Two</a></strong>
        """
        client = MagicMock()
        client.__enter__.return_value = client
        client.__exit__.return_value = None
        client.get.return_value = _HttpResponse(text=html)

        with patch("httpx.Client", return_value=client) as client_type:
            results = source_news._fetch_homepage_articles(
                limit=5,
                period="daily",
                anchor=date(2026, 7, 28),
                source_channel="techmeme_daily_rss",
                existing_urls={"https://rss.test/item"},
            )

        self.assertEqual([item["url"] for item in results], [
            "https://external.test/one",
            "https://external.test/two",
        ])
        self.assertEqual([item["rank_in_period"] for item in results], [2, 3])
        self.assertTrue(all(item["score"] == 1.5 for item in results))
        self.assertTrue(all(item["published_date"] == "2026-07-28" for item in results))
        kwargs = client_type.call_args.kwargs
        self.assertEqual(kwargs["timeout"], 20)
        self.assertTrue(kwargs["follow_redirects"])
        self.assertEqual(kwargs["headers"]["Accept-Language"], "en-US,en;q=0.9")
        client.get.assert_called_once_with(source_news.TECHMEME_HOME_URL)

    def test_fetch_is_rss_first_then_html_fill_with_normalized_period_and_anchor(self) -> None:
        rss = [{"url": "https://rss.test/one"}]
        html = [{"url": "https://html.test/two"}]

        with (
            patch.object(source_news, "_fetch_rss_articles", return_value=rss) as fetch_rss,
            patch.object(source_news, "_fetch_homepage_articles", return_value=html) as fetch_home,
        ):
            results = source_news.fetch_news_articles(
                limit=3,
                period=" DAILY ",
                target_date="2026-07-28",
            )

        self.assertEqual(results, rss + html)
        fetch_rss.assert_called_once_with(
            3,
            "daily",
            date(2026, 7, 28),
            "techmeme_daily_rss",
        )
        fetch_home.assert_called_once_with(
            limit=2,
            period="daily",
            anchor=date(2026, 7, 28),
            source_channel="techmeme_daily_rss",
            existing_urls={"https://rss.test/one"},
        )

    def test_rss_failure_is_empty_and_homepage_failure_preserves_rss(self) -> None:
        broken_client = MagicMock()
        broken_client.__enter__.return_value = broken_client
        broken_client.__exit__.return_value = None
        broken_client.get.side_effect = RuntimeError("offline")

        with patch("httpx.Client", return_value=broken_client):
            self.assertEqual(
                source_news._fetch_rss_articles(
                    10, "daily", date(2026, 7, 28), "techmeme_daily_rss"
                ),
                [],
            )

        rss = [{"url": "https://rss.test/one"}]
        with (
            patch.object(source_news, "_fetch_rss_articles", return_value=rss),
            patch.object(source_news, "_fetch_homepage_articles", return_value=[]),
        ):
            self.assertEqual(source_news.fetch_news_articles(limit=2), rss)

    def test_period_boundaries_keep_daily_yesterday_and_weekly_six_days(self) -> None:
        anchor = date(2026, 7, 28)
        self.assertTrue(source_news._within_period("2026-07-27", "daily", anchor))
        self.assertFalse(source_news._within_period("2026-07-26", "daily", anchor))
        self.assertTrue(source_news._within_period("2026-07-22", "weekly", anchor))
        self.assertFalse(source_news._within_period("2026-07-21", "weekly", anchor))
        self.assertTrue(source_news._within_period("", "daily", anchor))
        self.assertTrue(source_news._within_period("invalid", "daily", anchor))


class NewsCrawlerContracts(unittest.IsolatedAsyncioTestCase):
    async def test_crawler_forces_daily_and_preserves_requested_snapshot(self) -> None:
        items = [{"title": "Example"}]
        with patch.object(
            news_crawler,
            "fetch_news_articles",
            return_value=items,
        ) as fetch:
            result = await news_crawler.NewsCrawler()._do_fetch(
                period="weekly",
                limit=7,
                target_date="2026-07-20",
            )

        fetch.assert_called_once_with(
            limit=7,
            period="daily",
            target_date="2026-07-20",
        )
        self.assertEqual(result.period, "daily")
        self.assertEqual(result.snapshot_date, "2026-07-20")
        self.assertEqual(result.source_channel, "techmeme_daily_rss")
        self.assertEqual(items[0]["source"], "news")
        self.assertEqual(items[0]["channel"], "techmeme_daily_rss")


if __name__ == "__main__":
    unittest.main()
