from __future__ import annotations

from backend.app.repositories.postgres_project_catalog import PostgresProjectCatalogRepository
from backend.tests.postgres_test_safety import postgres_test_sandbox


def test_hot_dates_skip_scan_lists_each_metric_date_once_newest_first():
    with postgres_test_sandbox() as sandbox:
        db = sandbox.database
        catalog = PostgresProjectCatalogRepository(db)
        assert catalog.list_github_hot_dates(limit=5) == []
        with db.transaction() as connection:
            connection.execute("""
                INSERT INTO github_repo_candidates (repo_id, full_name, title, stars)
                VALUES ('a/one', 'a/one', 'One', 900),
                       ('a/two', 'a/two', 'Two', 800),
                       ('a/three', 'a/three', 'Three', 700);
                INSERT INTO github_repo_daily_metrics (repo_id, metric_date)
                VALUES ('a/one', '2026-10-01'), ('a/two', '2026-10-01'), ('a/three', '2026-10-01'),
                       ('a/one', '2026-10-03'), ('a/two', '2026-10-03'),
                       ('a/three', '2026-09-28'),
                       ('a/one', '2026-10-04');
            """)
        assert catalog.list_github_hot_dates(limit=10) == [
            "2026-10-04", "2026-10-03", "2026-10-01", "2026-09-28",
        ]
        assert catalog.list_github_hot_dates(limit=2) == ["2026-10-04", "2026-10-03"]
        assert catalog.list_github_hot_dates(limit=1) == ["2026-10-04"]
