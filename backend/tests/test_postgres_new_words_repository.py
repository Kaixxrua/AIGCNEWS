from datetime import date, datetime, timedelta, timezone

import pytest
from psycopg.errors import CheckViolation

from backend.app.repositories.postgres_new_words_repository import PostgresNewWordsRepository
from backend.tests.postgres_test_safety import postgres_test_sandbox


def test_migration_and_daily_snapshot_repository_on_postgres():
    with postgres_test_sandbox() as sandbox:
        repo = PostgresNewWordsRepository(sandbox.database)
        day = date(2026, 10, 8)
        now = datetime(2026, 10, 8, 8, tzinfo=timezone.utc)
        with sandbox.database.transaction() as conn:
            conn.execute("""
                INSERT INTO documents (id, source, title, summary, url, published_at, created_at, retweeted_by)
                VALUES
                ('primary', 'arxiv', 'Paper', 'We introduce Prism Routing', 'https://arxiv.org/abs/1', '2026-10-07', '2026-10-08', NULL),
                ('old', 'arxiv', 'History', 'Prism Routing existed', 'https://arxiv.org/abs/2', '2025-01-01', '2026-10-08', NULL),
                ('undated', 'arxiv', 'Missing date', 'No evidence', 'https://arxiv.org/abs/3', NULL, '2026-10-08', NULL),
                ('x', 'x', 'Post', 'A repost', 'https://x.com/a/status/1', '2026-10-07', '2026-10-08', 'b')
            """)
        assert [d["id"] for d in repo.recent_documents(date(2026, 10, 1), day, ["arxiv"])] == ["primary"]
        assert repo.recent_documents(date(2026, 10, 1), day, ["x"])[0]["retweeted_by"] == "b"
        assert [d["id"] for d in repo.historical_mentions(["Prism Routing"], date(2026, 10, 1), ["arxiv"])] == ["old"]
        assert repo.historical_mentions(["%"], day, ["arxiv"]) == []
        assert repo.existing_ids(["primary", "x", "missing"], ["arxiv"]) == {"primary"}
        assert repo.get_snapshot(day) is None
        repo.save_snapshot(day, [{"term": "Prism Routing"}], now)
        repo.save_snapshot(day, [], now - timedelta(minutes=1))
        assert repo.get_snapshot(day)["items"] == [{"term": "Prism Routing"}]
        repo.save_snapshot(day + timedelta(days=1), [], now + timedelta(days=1))
        assert repo.get_snapshot(day)["items"] == [{"term": "Prism Routing"}]
        repo.save_snapshot(day - timedelta(days=2), [{"term": "Older Routing"}], now)
        assert repo.snapshot_dates(day + timedelta(days=2), 5) == [day, day - timedelta(days=2)]
        assert repo.snapshot_dates(day + timedelta(days=2), 1) == [day]
        assert repo.snapshot_dates(day, 5) == [day - timedelta(days=2)]
        with pytest.raises(CheckViolation):
            repo.save_snapshot(day, [{}, {}, {}], now + timedelta(hours=1))
        repo.save_snapshot(day, [], now + timedelta(hours=1))
        assert repo.get_snapshot(day)["items"] == []
