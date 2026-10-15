from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from hashlib import sha256

import psycopg
import pytest

from backend.app.core.postgres_migrations import PostgresMigrationRunner
from backend.app.repositories.postgres_account_visit_repository import PostgresAccountVisitRepository
from backend.app.repositories.postgres_visitor_return_repository import CST, PostgresVisitorReturnRepository
from backend.tests.postgres_test_safety import postgres_test_sandbox

MIDNIGHT = datetime(2026, 10, 11, 16, tzinfo=timezone.utc)  # Oct 12 in Shanghai
VISITOR = "anonymous-browser-1234567890"


@pytest.fixture
def database():
    with postgres_test_sandbox() as sandbox:
        with sandbox.database.transaction() as conn:
            conn.execute(
                "UPDATE site_visitor_tracking SET started_at = %s",
                (MIDNIGHT - timedelta(days=20),),
            )
            conn.execute(
                "UPDATE account_visit_tracking SET started_at = %s",
                (MIDNIGHT - timedelta(days=20),),
            )
        yield sandbox.database


def test_anonymous_return_survives_registration_and_uses_all_tracked_visitors(database):
    repo = PostgresVisitorReturnRepository(database)
    day = MIDNIGHT.astimezone(CST).date()
    repo.record(day - timedelta(days=12), VISITOR)  # Outside the seven-day display window.
    repo.record(day, VISITOR)
    with database.transaction() as conn:
        user = conn.execute(
            """INSERT INTO users (email, hashed_password, created_at)
               VALUES ('new@example.test', 'hash', %s) RETURNING id""", (MIDNIGHT,),
        ).fetchone()["id"]
    accounts = PostgresAccountVisitRepository(database)
    accounts.record(user, now=MIDNIGHT)
    repo.record(day, VISITOR)  # Same browser after registration/sign-in.
    repo.record(day, "first-time-browser-123456")
    stats = accounts.stats(7, now=MIDNIGHT + timedelta(hours=1))
    assert stats["days"][0]["new_users"] == 1
    browser = stats["visitor_returns"]
    assert len(browser["days"]) == 7
    assert browser["days"][0] == {
        "day": "2026-10-12", "coverage": "partial",
        "total_visitors": 2, "returning_visitors": 1, "return_rate": .5,
    }
    with database.transaction() as conn:
        conn.execute("DELETE FROM users WHERE id = %s", (user,))
    assert repo.stats(1, now=MIDNIGHT)["days"][0] == browser["days"][0]


def test_concurrent_retries_count_once_and_store_only_hashed_identity(database):
    day = MIDNIGHT.astimezone(CST).date()
    repo = PostgresVisitorReturnRepository(database)
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: repo.record(day, VISITOR), range(24)))
    row = PostgresVisitorReturnRepository(database).stats(1, now=MIDNIGHT)["days"][0]
    assert row["total_visitors"] == 1
    assert row["returning_visitors"] == 0
    assert row["return_rate"] == 0
    with database.transaction() as conn:
        history = conn.execute("SELECT * FROM site_visitor_history").fetchall()
        assert history == [{"visitor_hash": sha256(VISITOR.encode()).hexdigest(), "first_seen_day": day}]
        assert conn.execute("SELECT COUNT(*) AS n FROM site_visitor_days").fetchone()["n"] == 1


def test_cst_midnight_and_out_of_order_requests_preserve_earliest_visit(database):
    repo = PostgresVisitorReturnRepository(database)
    day = MIDNIGHT.astimezone(CST).date()
    repo.record(day, VISITOR)
    repo.record(day - timedelta(days=1), VISITOR)  # Delayed request from before midnight.
    assert repo.stats(1, now=MIDNIGHT - timedelta(microseconds=1))["days"][0] == {
        "day": "2026-10-11", "coverage": "partial",
        "total_visitors": 1, "returning_visitors": 0, "return_rate": 0,
    }
    assert repo.stats(1, now=MIDNIGHT)["days"][0]["return_rate"] == 1


def test_missing_history_first_day_empty_days_and_partial_coverage(database):
    with database.transaction() as conn:
        conn.execute("UPDATE site_visitor_tracking SET started_at = %s", (MIDNIGHT + timedelta(hours=1),))
        conn.execute("INSERT INTO site_visit_days (day, visits) VALUES ('2026-10-11', 453)")
    repo = PostgresVisitorReturnRepository(database)
    repo.record(MIDNIGHT.astimezone(CST).date(), VISITOR)
    rows = repo.stats(4, now=MIDNIGHT + timedelta(days=2))["days"]
    assert rows[0] == {"day": "2026-10-14", "coverage": "partial", "total_visitors": 0,
                       "returning_visitors": 0, "return_rate": None}
    assert rows[1]["coverage"] == "complete"
    assert rows[1]["return_rate"] is None
    assert rows[2] == {"day": "2026-10-12", "coverage": "partial", "total_visitors": 1,
                       "returning_visitors": None, "return_rate": None}
    assert rows[3] == {"day": "2026-10-11", "coverage": "unavailable", "total_visitors": None,
                       "returning_visitors": None, "return_rate": None}


def test_daily_write_failure_rolls_back_history_and_retry_succeeds(database):
    repo = PostgresVisitorReturnRepository(database)
    with database.transaction() as conn:
        conn.execute("""
            CREATE FUNCTION reject_visitor_day() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN RAISE EXCEPTION 'test write failure'; END $$;
            CREATE TRIGGER fail_visitor_day BEFORE INSERT ON site_visitor_days
            FOR EACH ROW EXECUTE FUNCTION reject_visitor_day();
        """)
    with pytest.raises(psycopg.errors.RaiseException, match="test write failure"):
        repo.record(MIDNIGHT.date(), VISITOR)
    with database.transaction() as conn:
        assert conn.execute("SELECT COUNT(*) AS n FROM site_visitor_history").fetchone()["n"] == 0
        assert conn.execute("SELECT COUNT(*) AS n FROM site_visitor_days").fetchone()["n"] == 0
        conn.execute("DROP TRIGGER fail_visitor_day ON site_visitor_days")
    repo.record(MIDNIGHT.astimezone(CST).date(), VISITOR)
    assert repo.stats(1, now=MIDNIGHT)["days"][0]["total_visitors"] == 1


def test_migration_is_repeatable_and_does_not_backfill_browser_history(database):
    with database.transaction() as conn:
        conn.execute("DROP TABLE site_visitor_days, site_visitor_history, site_visitor_tracking")
        conn.execute("DELETE FROM app_schema_migrations WHERE version = 99")
        conn.execute("INSERT INTO site_visit_days (day, visits) VALUES ('2026-10-09', 100)")
    runner = PostgresMigrationRunner(database)
    assert [migration.version for migration in runner.apply()] == [99]
    assert runner.apply() == []
    with database.transaction() as conn:
        assert conn.execute("SELECT COUNT(*) AS n FROM site_visitor_history").fetchone()["n"] == 0
        assert conn.execute("SELECT visits FROM site_visit_days WHERE day = '2026-10-09'").fetchone()["visits"] == 100


def test_invalid_browser_identity_is_rejected_before_database_access():
    repo = PostgresVisitorReturnRepository(None)
    with pytest.raises(ValueError):
        repo.record(MIDNIGHT.date(), "invalid")
