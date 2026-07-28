from __future__ import annotations

import unittest
from datetime import date

from backend.app.services.ingestion.sources import hackernews_policy, news_policy


class NewsPolicyTests(unittest.TestCase):
    def test_rss_projection_preserves_cap_rank_and_period_filter(self) -> None:
        entries = [
            {
                "title": f"Story {index}",
                "summary": "<b>Summary</b>",
                "link": f"https://example.test/{index}",
                "published": "Mon, 28 Jul 2026 12:00:00 GMT",
            }
            for index in range(20)
        ]

        results = news_policy.project_rss_entries(
            entries,
            limit=30,
            period="daily",
            anchor=date(2026, 7, 28),
            source_channel="techmeme_daily_rss",
        )

        self.assertEqual(len(results), 15)
        self.assertEqual(results[0]["summary"], "Summary")
        self.assertEqual(results[-1]["rank_in_period"], 15)
        self.assertTrue(all(item["score"] == 2.0 for item in results))

    def test_homepage_projection_deduplicates_and_excludes_internal_urls(self) -> None:
        results = news_policy.project_homepage_matches(
            [
                ("https://rss.test/one", "Duplicate"),
                ("https://www.techmeme.com/inside", "Internal"),
                ("https://external.test/one", "<b>External</b>"),
            ],
            limit=5,
            period="daily",
            anchor=date(2026, 7, 28),
            source_channel="techmeme_daily_rss",
            existing_urls={"https://rss.test/one"},
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["title"], "External")
        self.assertEqual(results[0]["rank_in_period"], 2)
        self.assertEqual(results[0]["score"], 1.5)


class HackerNewsPolicyTests(unittest.TestCase):
    def test_acceptance_recent_cutoff_and_score_order(self) -> None:
        now_ts = 1_800_000_000.0
        stories = [
            {"id": 1, "type": "story", "score": 10, "time": now_ts - 1},
            {"id": 2, "type": "story", "score": 50, "time": now_ts - 86400},
            {"id": 3, "type": "story", "score": 100, "time": now_ts - 86401},
        ]

        self.assertTrue(hackernews_policy.is_story(stories[0]))
        self.assertFalse(hackernews_policy.is_story({"type": "story", "dead": True}))
        recent = hackernews_policy.filter_recent_stories(stories, now_ts=now_ts)
        ordered = hackernews_policy.sort_by_score(recent)

        self.assertEqual([story["id"] for story in ordered], [2, 1])

    def test_projection_preserves_fallback_url_and_exact_fields(self) -> None:
        results = hackernews_policy.project_stories(
            [
                {
                    "id": 42,
                    "type": "story",
                    "title": "Example",
                    "score": 7,
                    "descendants": 3,
                    "time": 1_800_000_000,
                    "by": "author",
                }
            ],
            limit=1,
        )

        self.assertEqual(results[0]["url"], "https://news.ycombinator.com/item?id=42")
        self.assertEqual(results[0]["rank_in_period"], 1)
        self.assertEqual(results[0]["score"], 7.0)
        self.assertEqual(results[0]["tags"], ["hackernews", "daily", "top30"])


if __name__ == "__main__":
    unittest.main()
