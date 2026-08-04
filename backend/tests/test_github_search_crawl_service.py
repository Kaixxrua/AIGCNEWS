from __future__ import annotations

import unittest
from datetime import date

import pytest

from backend.app.services.ingestion.github_search_crawl import (
    _stars_query,
    crawl_github_search,
)


class FakeSearchClient:
    """按 (query, page) 提供罐装响应；per_page=1 调用视为分片计数。"""

    def __init__(
        self,
        counts: dict[str, int],
        pages: dict[tuple[str, int], list[dict]],
    ) -> None:
        self._counts = counts
        self._pages = pages
        self.requests = 0
        self.search_calls: list[tuple[str, int, int]] = []
        self.closed = False

    def total_count(self, query: str) -> int:
        return int(self.search(query, per_page=1).get("total_count") or 0)

    def search(self, query: str, *, per_page: int = 100, page: int = 1) -> dict:
        self.requests += 1
        self.search_calls.append((query, per_page, page))
        if per_page == 1:
            return {"total_count": self._counts.get(query, 0), "items": []}
        return {
            "total_count": self._counts.get(query, 0),
            "items": self._pages.get((query, page), []),
        }

    def close(self) -> None:
        self.closed = True


class FakeIngestion:
    def __init__(self, existing: dict[str, str] | None = None) -> None:
        self._existing = existing or {}
        self.upserted: list[dict] = []
        self.channel_queries: list[list[str]] = []

    def get_github_repo_source_channels(self, repo_ids: list[str]) -> dict[str, str]:
        self.channel_queries.append(list(repo_ids))
        return {rid: self._existing[rid] for rid in repo_ids if rid in self._existing}

    def upsert_github_repo_candidate(self, payload: dict) -> None:
        self.upserted.append(dict(payload))


def _item(full_name: str, stars: int) -> dict:
    return {
        "full_name": full_name,
        "html_url": f"https://github.com/{full_name}",
        "description": "demo",
        "language": "Python",
        "topics": ["llm"],
        "created_at": "2025-02-01T00:00:00Z",
        "pushed_at": "2026-01-01T00:00:00Z",
        "stargazers_count": stars,
        "forks_count": 5,
        "watchers_count": stars,
    }


ONE_DAY_QUERY = _stars_query(500, 0, date(2026, 1, 1), date(2026, 1, 1))


class GitHubSearchCrawlServiceTests(unittest.TestCase):
    def test_dry_run_counts_shards_without_paging_or_writes(self) -> None:
        client = FakeSearchClient({ONE_DAY_QUERY: 42}, {})
        ingestion = FakeIngestion()

        summary = crawl_github_search(
            min_stars=500,
            max_stars=0,
            limit=5000,
            created_start=date(2026, 1, 1),
            created_end=date(2026, 1, 1),
            channel="chan_test",
            dry_run=True,
            ingestion=ingestion,
            client=client,
        )

        assert summary["status"] == "dry_run"
        assert summary["shards"] == {"2026-01-01..2026-01-01": 42}
        assert summary["total_available"] == 42
        assert summary["api_requests"] == 1
        # dry-run 只允许 per_page=1 的计数请求，绝不翻页
        assert all(per_page == 1 for _, per_page, _ in client.search_calls)
        assert ingestion.upserted == []
        assert ingestion.channel_queries == []
        assert "fetched" not in summary

    def test_crawl_filters_dedupes_merges_channels_and_reports_summary(self) -> None:
        client = FakeSearchClient(
            {ONE_DAY_QUERY: 150},
            {
                (ONE_DAY_QUERY, 1): [
                    _item("a/one", 800),
                    _item("a/low", 499),
                    _item("a/two", 900),
                ],
                (ONE_DAY_QUERY, 2): [
                    _item("A/One", 700),  # 大小写不同也视为重复
                    _item("a/three", 600),
                ],
            },
        )
        ingestion = FakeIngestion(existing={"a/two": "trending_daily"})

        summary = crawl_github_search(
            min_stars=500,
            max_stars=0,
            limit=5000,
            created_start=date(2026, 1, 1),
            created_end=date(2026, 1, 1),
            channel="chan_test",
            ingestion=ingestion,
            client=client,
        )

        assert summary["status"] == "success"
        assert summary["fetched"] == 5
        assert summary["upserted"] == 3
        assert summary["new_candidates"] == 2
        assert summary["existing_candidates_updated"] == 1
        assert summary["skipped_low_stars"] == 1
        assert summary["skipped_duplicates"] == 1

        by_repo = {p["repo_id"]: p for p in ingestion.upserted}
        assert set(by_repo) == {"a/one", "a/two", "a/three"}
        # 已有行合并既有渠道 + 本次渠道标记；新行只带本次标记
        assert by_repo["a/two"]["source_channels"] == "trending_daily,chan_test"
        assert by_repo["a/one"]["source_channels"] == "chan_test"
        assert by_repo["a/one"]["stars"] == 800
        assert by_repo["a/one"]["topics_json"] == '["llm"]'

    def test_crawl_stops_at_limit(self) -> None:
        client = FakeSearchClient(
            {ONE_DAY_QUERY: 150},
            {
                (ONE_DAY_QUERY, 1): [
                    _item("a/one", 800),
                    _item("a/low", 499),
                    _item("a/two", 900),
                ],
                (ONE_DAY_QUERY, 2): [_item("a/three", 600)],
            },
        )
        ingestion = FakeIngestion()

        summary = crawl_github_search(
            min_stars=500,
            max_stars=0,
            limit=2,
            created_start=date(2026, 1, 1),
            created_end=date(2026, 1, 1),
            channel="chan_test",
            ingestion=ingestion,
            client=client,
        )

        assert summary["upserted"] == 2
        assert {p["repo_id"] for p in ingestion.upserted} == {"a/one", "a/two"}
        # 到达上限后不再请求第 2 页数据
        assert (ONE_DAY_QUERY, 100, 2) not in client.search_calls

    def test_validation_rejects_bad_windows(self) -> None:
        base = dict(
            min_stars=500,
            max_stars=0,
            limit=10,
            created_start=date(2026, 1, 1),
            created_end=date(2026, 1, 1),
            channel="chan_test",
            dry_run=True,
        )
        with pytest.raises(ValueError, match="max_stars"):
            crawl_github_search(**{**base, "max_stars": 400})
        with pytest.raises(ValueError, match="created_end"):
            crawl_github_search(
                **{**base, "created_start": date(2026, 2, 1), "created_end": date(2026, 1, 1)}
            )
        with pytest.raises(ValueError, match="pushed_after"):
            crawl_github_search(**{**base, "pushed_after": "2025-13-40"})
        with pytest.raises(ValueError, match="channel"):
            crawl_github_search(**{**base, "channel": "  "})

    def test_formal_run_requires_ingestion_repository(self) -> None:
        with pytest.raises(ValueError, match="ingestion"):
            crawl_github_search(
                min_stars=500,
                max_stars=0,
                limit=10,
                created_start=date(2026, 1, 1),
                created_end=date(2026, 1, 1),
                channel="chan_test",
                dry_run=False,
                ingestion=None,
                client=FakeSearchClient({}, {}),
            )


if __name__ == "__main__":
    unittest.main()
