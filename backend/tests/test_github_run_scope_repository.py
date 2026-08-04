from __future__ import annotations

import contextlib
import unittest

from backend.app.repositories.postgres_project_enrichment_repository import (
    PostgresGitHubProjectEnrichmentRepository,
    _github_fingerprint,
)
from backend.app.repositories.postgres_project_ingestion_repository import (
    PostgresGitHubProjectIngestionRepository,
)


class FakeCursor:
    def __init__(self, results: list) -> None:
        self._results = list(results)
        self.calls: list[tuple[str, tuple]] = []
        self._current = []

    def execute(self, sql, params=()) -> None:
        self.calls.append((sql, tuple(params)))
        self._current = self._results.pop(0)

    def fetchall(self):
        return self._current

    def fetchone(self):
        return self._current[0] if self._current else None


class FakeDB:
    def __init__(self, results: list) -> None:
        self.fake_cursor = FakeCursor(results)

    @contextlib.contextmanager
    def transaction(self):
        yield self

    @contextlib.contextmanager
    def cursor(self):
        yield self.fake_cursor


class ExplodingCursor:
    def execute(self, sql, params=()) -> None:  # pragma: no cover - 不应被触达
        raise AssertionError("空列表短路，不应执行任何 SQL")


class ExplodingDB:
    @contextlib.contextmanager
    def transaction(self):
        yield self

    @contextlib.contextmanager
    def cursor(self):
        yield ExplodingCursor()


ANCHOR = "2026-08-04T00:00:00+00:00"


def _candidate_row(repo_id: str = "a/b") -> dict:
    return {
        "repo_id": repo_id,
        "full_name": repo_id,
        "title": repo_id,
        "url": f"https://github.com/{repo_id}",
        "description": "demo",
        "language": "Python",
        "topics_json": '["llm"]',
        "created_at": "2025-02-01",
        "pushed_at": "2026-01-01",
        "source_channels": "chan",
        "first_seen_at": "2026-08-04T06:40:00+00:00",
        "last_seen_at": "2026-08-04T06:40:00+00:00",
        "last_snapshot_at": "2026-08-04T06:40:00+00:00",
        "stars": 800,
        "forks": 5,
        "watchers": 800,
    }


class GitHubRunScopeRepositoryTests(unittest.TestCase):
    def test_count_scopes_params_to_channel_anchor_and_stars(self) -> None:
        db = FakeDB([[{"n": 7}]])
        repository = PostgresGitHubProjectEnrichmentRepository(db)

        total = repository.count_github_run_enrichment_candidates(
            channel="chan", first_seen_after=ANCHOR, min_stars=500
        )

        assert total == 7
        sql, params = db.fake_cursor.calls[0]
        assert params == ("%chan%", ANCHOR, 500)
        assert "source_channels LIKE" in sql
        assert "first_seen_at >=" in sql
        assert "NOT EXISTS" in sql
        assert "github_repo_enrichments" in sql
        assert "succeeded" in sql

    def test_list_uses_keyset_pagination_and_returns_fingerprint(self) -> None:
        db = FakeDB([[_candidate_row()]])
        repository = PostgresGitHubProjectEnrichmentRepository(db)

        rows = repository.list_github_run_enrichment_candidates(
            channel="chan",
            first_seen_after=ANCHOR,
            min_stars=500,
            after_repo_id="a/a",
            limit=50,
        )

        sql, params = db.fake_cursor.calls[0]
        assert params == ("%chan%", ANCHOR, 500, "a/a", 50)
        assert "c.repo_id > %s" in sql
        assert "ORDER BY c.repo_id" in sql

        assert len(rows) == 1
        row = rows[0]
        assert row["repo_id"] == "a/b"
        assert row["topics"] == ["llm"]
        assert row["stars"] == 800
        assert row["source_fingerprint"] == _github_fingerprint(
            {
                "full_name": "a/b",
                "description": "demo",
                "language": "Python",
                "topics_json": '["llm"]',
            }
        )

    def test_list_caps_limit(self) -> None:
        db = FakeDB([[]])
        repository = PostgresGitHubProjectEnrichmentRepository(db)

        rows = repository.list_github_run_enrichment_candidates(
            channel="chan", first_seen_after=ANCHOR, min_stars=500, limit=9999
        )

        assert rows == []
        _, params = db.fake_cursor.calls[0]
        assert params[-1] == 500

    def test_status_counts_with_filters_in_one_query(self) -> None:
        db = FakeDB([
            [
                {
                    "candidates_upserted": 10,
                    "scope_total": 8,
                    "enriched_succeeded": 5,
                    "enriched_failed": 1,
                }
            ]
        ])
        repository = PostgresGitHubProjectEnrichmentRepository(db)

        status = repository.get_github_run_crawl_status(
            channel="chan", first_seen_after=ANCHOR, min_stars=500
        )

        assert status == {
            "candidates_upserted": 10,
            "scope_total": 8,
            "enriched_succeeded": 5,
            "enriched_failed": 1,
        }
        sql, params = db.fake_cursor.calls[0]
        # 三个 FILTER 的 min_stars 在前，渠道与锚点在后
        assert params == (500, 500, 500, "%chan%", ANCHOR)
        assert sql.count("FILTER") == 3
        assert "LEFT JOIN github_repo_enrichments" in sql
        assert "NOT EXISTS" not in sql

    def test_source_channels_query_short_circuits_on_empty_ids(self) -> None:
        repository = PostgresGitHubProjectIngestionRepository(ExplodingDB())

        assert repository.get_github_repo_source_channels([]) == {}

    def test_source_channels_query_maps_rows(self) -> None:
        db = FakeDB([
            [
                {"repo_id": "a/b", "channels": "trending_daily"},
                {"repo_id": "c/d", "channels": ""},
            ]
        ])
        repository = PostgresGitHubProjectIngestionRepository(db)

        channels = repository.get_github_repo_source_channels(["a/b", "c/d"])

        assert channels == {"a/b": "trending_daily", "c/d": ""}
        sql, params = db.fake_cursor.calls[0]
        assert "repo_id = ANY(%s)" in sql
        assert params == (["a/b", "c/d"],)


if __name__ == "__main__":
    unittest.main()
