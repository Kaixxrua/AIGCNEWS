from datetime import date, timedelta

import pytest
from psycopg.errors import CheckViolation

from backend.app.repositories.postgres_project_catalog import PostgresProjectCatalogRepository
from backend.app.repositories.postgres_project_ingestion_repository import PostgresGitHubProjectIngestionRepository
from backend.app.services.ingestion.github_project_metrics_service import compute_github_daily_metrics
from backend.tests.postgres_test_safety import postgres_test_sandbox


def test_streak_uses_global_prior_public_boards_and_breaks_at_gaps():
    today = date(2026, 10, 11)
    appearances = {
        "leader": (100, range(1, 8)), "anchor": (95, range(1, 6)),
        "repeat": (90, [1, 2]), "second": (85, [1]), "gap": (80, [1, 3, 4, 5]),
        "absent": (75, [2, 3, 4, 5]), "outsider": (70, range(1, 6)), "new": (0, []),
        "pending": (200, range(1, 6)), "alias": (200, range(1, 6)),
        "quarantined": (200, range(1, 6)), "removed": (200, range(1, 6)),
        "zero": (200, range(1, 6)),
    }
    with postgres_test_sandbox() as sandbox:
        db = sandbox.database
        repository = PostgresGitHubProjectIngestionRepository(db)
        catalog = PostgresProjectCatalogRepository(db)
        for name, (score, days) in appearances.items():
            repo_id = f"streak/{name}"
            repository.upsert_github_repo_candidate({"repo_id": repo_id, "full_name": repo_id, "stars": 1200})
            repository.insert_github_repo_snapshot({
                "repo_id": repo_id, "snapshot_date": today.isoformat(),
                "captured_at": f"{today}T12:00:00+00:00", "stars": 1200,
            })
            with db.transaction() as connection:
                connection.execute(
                    """INSERT INTO github_repo_enrichments
                    (repo_id,category_slug,category_name,description_zh,source_fingerprint,prompt_version,status)
                    VALUES (%s,'tools','Tools','','fingerprint','test',%s)""",
                    (repo_id, "pending" if name == "pending" else "succeeded"),
                )
            repository.upsert_github_daily_metrics([
                {"repo_id": repo_id, "metric_date": (today - timedelta(days=ago)).isoformat(),
                 "stars": 1000, "hot_score": score, "score_version": "daily_hot_v8",
                 "daily_growth_available": True, "daily_star_growth": 200,
                 "rolling_24h_star_growth": 0 if name == "zero" else 200}
                # Today and future rows must not count, even if they lead.
                for ago in [*days, 0, -1]
            ])
        with db.transaction() as connection:
            connection.execute(
                "INSERT INTO github_repo_aliases(alias_repo_id,canonical_repo_id,full_name)"
                " VALUES ('streak/alias','streak/leader','streak/alias')",
            )
            connection.execute(
                "INSERT INTO github_repo_quarantine(repo_id,reason) VALUES ('streak/quarantined','name_reuse')",
            )
            connection.execute("UPDATE github_repo_candidates SET availability_status='not_found' WHERE repo_id='streak/removed'")

        def inputs(repo_ids=None):
            return repository.get_github_daily_metric_inputs(
                metric_date=str(today), previous_date=str(today - timedelta(days=1)),
                baseline_start_date=str(today - timedelta(days=7)), repo_ids=repo_ids,
            )

        all_rows = {row["repo_id"]: row["previous_top_streak_days"] for row in inputs()}
        expected = {"leader": 5, "anchor": 5, "repeat": 2, "second": 1, "gap": 1}
        for name in appearances:
            assert all_rows[f"streak/{name}"] == expected.get(name, 0)
        # Share the real public board's eligibility and tie-breaking contract.
        yesterday = catalog.list_github_hot_for_date(metric_date="2026-10-10", limit=5)
        assert {row["repo_id"] for row in yesterday} == {f"streak/{name}" for name in expected}
        assert inputs(["streak/outsider"])[0]["previous_top_streak_days"] == 0
        assert inputs(["streak/repeat"])[0]["previous_top_streak_days"] == 2

        # Persistence and same-day reruns apply the multiplier once.
        repository.upsert_github_trending_hit({
            "repo_id": "streak/leader", "full_name": "streak/leader", "period": "daily",
            "rank": 1, "observed_date": str(today), "captured_at": f"{today}T12:00:00+00:00",
            "period_star_growth": 200,
        })
        scores = []
        for _ in range(2):
            compute_github_daily_metrics(metric_date=str(today), repo_ids=["streak/leader"], db=repository)
            with db.transaction() as connection:
                row = connection.execute(
                    "SELECT * FROM github_repo_daily_metrics WHERE repo_id='streak/leader' AND metric_date=%s",
                    (str(today),),
                ).fetchone()
            assert row["previous_top_streak_days"] == 5 and row["score_version"] == "daily_hot_v9"
            scores.append(row["hot_score"])
        assert scores[0] > 0 and scores[1] == scores[0]

        # A missing calendar slice resets everyone, rather than bridging it.
        with db.transaction() as connection:
            connection.execute("DELETE FROM github_repo_daily_metrics WHERE metric_date='2026-10-10'")
        assert all(row["previous_top_streak_days"] == 0 for row in inputs())


def test_streak_column_default_keeps_legacy_rows_unpenalized():
    with postgres_test_sandbox() as sandbox:
        with sandbox.database.transaction() as connection:
            connection.execute("INSERT INTO github_repo_candidates(repo_id,full_name) VALUES ('old/repo','old/repo')")
            connection.execute(
                "INSERT INTO github_repo_daily_metrics(repo_id,metric_date,hot_score,score_version)"
                " VALUES ('old/repo','2026-10-10',75.5,'daily_hot_v8')",
            )
            row = connection.execute("SELECT * FROM github_repo_daily_metrics").fetchone()
            assert row["previous_top_streak_days"] == 0
            assert row["hot_score"] == 75.5 and row["score_version"] == "daily_hot_v8"
            with pytest.raises(CheckViolation):
                with connection.transaction():
                    connection.execute("UPDATE github_repo_daily_metrics SET previous_top_streak_days=6")
