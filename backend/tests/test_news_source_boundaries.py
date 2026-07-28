from __future__ import annotations

import ast
import unittest
from pathlib import Path


class NewsSourceBoundaryTests(unittest.TestCase):
    def test_source_facades_delegate_transport_and_policy_ownership(self) -> None:
        source_directory = Path(__file__).parents[1] / "app" / "services" / "ingestion"
        expectations = {
            "source_news.py": {
                "required": {"TechmemeTransport", "news_policy"},
                "forbidden": {"httpx", "feedparser", "parsedate_to_datetime"},
            },
            "source_hackernews.py": {
                "required": {"HackerNewsTransport", "hackernews_policy"},
                "forbidden": {"AsyncClient"},
            },
        }

        for filename, expectation in expectations.items():
            with self.subTest(filename=filename):
                module = ast.parse(
                    (source_directory / filename).read_text(encoding="utf-8")
                )
                imported = {
                    alias.asname or alias.name
                    for node in ast.walk(module)
                    if isinstance(node, (ast.Import, ast.ImportFrom))
                    for alias in node.names
                }
                self.assertTrue(expectation["required"] <= imported)
                self.assertFalse(expectation["forbidden"] & imported)

    def test_stable_public_source_functions_remain_available(self) -> None:
        from backend.app.services.ingestion import source_hackernews, source_news

        self.assertTrue(callable(source_news.fetch_news_articles))
        self.assertTrue(callable(source_hackernews.fetch_hackernews_items_async))
        self.assertTrue(callable(source_hackernews.fetch_hackernews_items))


if __name__ == "__main__":
    unittest.main()
