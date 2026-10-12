from datetime import date, timedelta

import pytest
from psycopg.errors import CheckViolation

from backend.app.repositories.postgres_project_catalog import PostgresProjectCatalogRepository
from backend.app.repositories.postgres_project_ingestion_repository import PostgresGitHubProjectIngestionRepository
from backend.app.services.ingestion.github_project_metrics_service import compute_github_daily_metrics
from backend.tests.postgres_test_safety import postgres_test_sandbox


def test_streak_uses_global_prior_public_boards_and_resets_after_three_absent_days():
    today = date(2026, 10, 11)
    appearances = {
        "leader": (100, range(1, 8)), "anchor": (95, range(1, 6)),
        "repeat": (90, [1, 2]), "second": (85, [1]), "gap": (80, [1, 3, 4, 5]),
        "sixth": (70, range(1, 6)), "seventh": (68, range(1, 6)),
        "eighth": (66, range(1, 6)), "ninth": (64, range(1, 6)), "tenth": (62, range(1, 6)),
        "absent": (75, [2, 3, 4, 5]), "outsider": (60, range(1, 6)), "new": (0, []),
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
        expected = {
            "leader": 5, "anchor": 5, "repeat": 2, "second": 1, "gap": 4,
            "sixth": 5, "seventh": 5, "eighth": 5, "ninth": 5, "tenth": 5,
            "absent": 4, "outsider": 4,
        }
        for name in appearances:
            assert all_rows[f"streak/{name}"] == expected.get(name, 0)
        # Share the real public board's eligibility and tie-breaking contract.
        yesterday = catalog.list_github_hot_for_date(metric_date="2026-10-10", limit=11)
        assert yesterday[9]["repo_id"] == "streak/tenth"
        assert yesterday[10]["repo_id"] == "streak/outsider"
        yesterday = yesterday[:10]
        assert {row["repo_id"] for row in yesterday} == {
            f"streak/{name}" for name in expected if name not in ("absent", "outsider")
        }
        assert inputs(["streak/outsider"])[0]["previous_top_streak_days"] == 4
        assert inputs(["streak/repeat"])[0]["previous_top_streak_days"] == 2
        for name in ("sixth", "seventh", "eighth", "ninth", "tenth"):
            assert inputs([f"streak/{name}"])[0]["previous_top_streak_days"] == 5

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
            assert row["previous_top_streak_days"] == 5 and row["score_version"] == "daily_hot_v11"
            scores.append(row["hot_score"])
        assert scores[0] > 0 and scores[1] == scores[0]

        # Missing slices count as absent days; only three in a row reset.
        for missing_days in (1, 2, 3):
            with db.transaction() as connection:
                connection.execute(
                    "DELETE FROM github_repo_daily_metrics WHERE metric_date=%s",
                    (str(today - timedelta(days=missing_days)),),
                )
            remaining = {row["repo_id"]: row["previous_top_streak_days"] for row in inputs()}
            assert remaining["streak/leader"] == (5 if missing_days < 3 else 0)
        assert all(count == 0 for count in remaining.values())


@pytest.mark.parametrize(("appearance_days", "expected"), [
    ([2, 3, 4], 3),             # One absent day preserves the count.
    ([3, 4, 5], 3),             # Two absent days preserve it without incrementing.
    ([4, 5, 6], 0),             # Three absent days reset it.
    ([1, 3, 4], 3),             # Re-entry after one absent day continues the run.
    ([1, 4, 5], 3),             # Re-entry after two absent days continues the run.
    ([1, 5, 6], 1),             # Re-entry after three absent days starts fresh.
    ([1, 2, 5, 9, 10], 3),     # An older reset excludes only the earlier run.
    ([3, 6, 9, 12, 15], 5),    # Repeated two-day gaps still reach the cap.
    ([3, 6, 9, 12], 4),        # Gaps themselves never count as appearances.
])
def test_cooldown_counts_public_top_ten_appearances_not_off_board_days(appearance_days, expected):
    today = date(2026, 10, 20)
    with postgres_test_sandbox() as sandbox:
        db = sandbox.database
        repository = PostgresGitHubProjectIngestionRepository(db)
        # Ten fillers keep the target in eleventh place on each off-board day.
        for index in range(11):
            repo_id = f"cooldown/repo-{index}"
            repository.upsert_github_repo_candidate({"repo_id": repo_id, "full_name": repo_id, "stars": 1200})
            with db.transaction() as connection:
                connection.execute(
                    """INSERT INTO github_repo_enrichments
                    (repo_id,category_slug,category_name,description_zh,source_fingerprint,prompt_version,status)
                    VALUES (%s,'tools','Tools','','fingerprint','test','succeeded')""",
                    (repo_id,),
                )
            repository.upsert_github_daily_metrics([
                {"repo_id": repo_id, "metric_date": str(today - timedelta(days=ago)),
                 "stars": 1200, "hot_score": (100 if ago in appearance_days else 1) if index == 0 else 90-index,
                 "score_version": "daily_hot_v10", "daily_growth_available": True, "daily_star_growth": 100}
                for ago in range(1, 17)
            ])
        repository.insert_github_repo_snapshot({
            "repo_id": "cooldown/repo-0", "snapshot_date": str(today),
            "captured_at": f"{today}T12:00:00+00:00", "stars": 1300,
        })
        rows = repository.get_github_daily_metric_inputs(
            metric_date=str(today), previous_date=str(today - timedelta(days=1)),
            baseline_start_date=str(today - timedelta(days=7)), repo_ids=["cooldown/repo-0"],
        )
        assert len(rows) == 1
        assert rows[0]["previous_top_streak_days"] == expected


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
