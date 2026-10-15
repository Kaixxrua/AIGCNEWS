from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from backend.app.repositories.postgres_account_visit_repository import PostgresAccountVisitRepository
from backend.app.repositories.postgres_email_monitor_repository import PostgresEmailMonitorRepository
from backend.tests.postgres_test_safety import postgres_test_sandbox

MIDNIGHT = datetime(2026, 10, 9, 16, tzinfo=timezone.utc)  # Oct 10 in Shanghai


@pytest.fixture
def database():
    with postgres_test_sandbox() as sandbox:
        with sandbox.database.transaction() as conn:
            conn.execute("UPDATE account_visit_tracking SET started_at = %s", (MIDNIGHT - timedelta(hours=12),))
        yield sandbox.database


def user(database, created_at):
    with database.transaction() as conn:
        return conn.execute(
            "INSERT INTO users (email, hashed_password, created_at) VALUES (%s, 'hash', %s) RETURNING id",
            (f"{uuid4()}@example.test", created_at),
        ).fetchone()["id"]


def visitor_count(database, day, count):
    with database.transaction() as conn:
        conn.execute("INSERT INTO site_visit_days (day, visits) VALUES (%s, %s)", (day, count))


def test_concurrent_devices_and_retries_count_account_once(database):
    repo = PostgresAccountVisitRepository(database)
    owner = user(database, MIDNIGHT - timedelta(days=1))
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: repo.record(owner, now=MIDNIGHT), range(24)))
    # A new worker/restart and later retries still share the database identity.
    assert PostgresAccountVisitRepository(database).record(owner, now=MIDNIGHT)["recorded"]
    visitor_count(database, "2026-10-10", 10)
    result = repo.stats(1, now=MIDNIGHT + timedelta(hours=2))
    assert result["days"][0] == {
        "day": "2026-10-10", "coverage": "partial", "active_users": 1,
        "returning_users": 1, "new_users": 0, "total_visitors": 10, "return_rate": .1,
        "registration_rate": 0,
    }


def test_exact_cst_boundary_and_registration_cutoff(database):
    repo = PostgresAccountVisitRepository(database)
    old = user(database, MIDNIGHT - timedelta(microseconds=1))
    new = user(database, MIDNIGHT)
    repo.record(old, now=MIDNIGHT - timedelta(microseconds=1))
    repo.record(old, now=MIDNIGHT)
    receipt = repo.record(new, now=MIDNIGHT)
    visitor_count(database, "2026-10-09", 4)
    visitor_count(database, "2026-10-10", 10)
    result = repo.stats(4, now=MIDNIGHT + timedelta(hours=23))
    assert result["timezone"] == "Asia/Shanghai"
    assert result["days"][0]["return_rate"] == pytest.approx(1 / 9)
    assert result["days"][0]["registration_rate"] == pytest.approx(1 / 9)
    assert result["days"][0]["total_visitors"] == 10
    assert result["days"][0]["active_users"] == 2
    assert result["days"][1]["return_rate"] == 0  # registered on Oct 9, visited Oct 9
    assert result["days"][1]["registration_rate"] == .25
    assert result["days"][1]["coverage"] == "partial"
    assert result["days"][2]["active_users"] is None
    assert result["days"][2]["return_rate"] is None
    assert result["days"][2]["registration_rate"] is None
    assert receipt["next_day_at"] == "2026-10-11T00:00:00+08:00"
    repo.record(new, now=MIDNIGHT + timedelta(days=1))
    visitor_count(database, "2026-10-11", 1)
    next_day = repo.stats(1, now=MIDNIGHT + timedelta(days=1))["days"][0]
    assert next_day["return_rate"] == 1
    assert next_day["registration_rate"] is None


def test_empty_days_disabled_accounts_and_deleted_history(database):
    repo = PostgresAccountVisitRepository(database)
    owner = user(database, MIDNIGHT - timedelta(days=1))
    repo.record(owner, now=MIDNIGHT)
    with database.transaction() as conn:
        conn.execute("UPDATE users SET disabled = TRUE WHERE id = %s", (owner,))
    assert not repo.record(owner, now=MIDNIGHT + timedelta(days=1))["recorded"]
    with database.transaction() as conn:
        conn.execute("DELETE FROM users WHERE id = %s", (owner,))
    rows = repo.stats(3, now=MIDNIGHT + timedelta(days=2))["days"]
    assert rows[0]["return_rate"] is None
    assert rows[0]["registration_rate"] is None
    assert rows[1]["active_users"] == 0
    assert rows[1]["coverage"] == "complete"
    assert rows[2]["active_users"] == 1  # account deletion does not rewrite history


def test_denominator_includes_anonymous_visitors_and_handles_missing_history(database):
    repo = PostgresAccountVisitRepository(database)
    visitor_count(database, "2026-10-08", 12)  # UV history predates account tracking.
    visitor_count(database, "2026-10-09", 5)  # Anonymous-only day is still known.
    visitor_count(database, "2026-10-10", 10)
    for registered_at in (MIDNIGHT - timedelta(days=2), MIDNIGHT - timedelta(days=1), MIDNIGHT):
        repo.record(user(database, registered_at), now=MIDNIGHT)
    rows = repo.stats(4, now=MIDNIGHT + timedelta(hours=1))["days"]
    assert rows[0]["active_users"] == 3
    assert rows[0]["returning_users"] == 2
    assert rows[0]["total_visitors"] == 10
    assert rows[0]["return_rate"] == pytest.approx(2 / 9)  # Exclude the one same-day new account.
    assert rows[0]["registration_rate"] == .125  # Exclude two visiting existing accounts.
    assert rows[1]["active_users"] == 0
    assert rows[1]["total_visitors"] == 5
    assert rows[1]["return_rate"] == 0
    assert rows[1]["registration_rate"] == 0
    assert rows[2]["total_visitors"] == 12
    assert rows[2]["return_rate"] is None  # Cannot infer historical returning accounts.
    assert rows[2]["registration_rate"] is None
    assert rows[3]["total_visitors"] is None


def test_missing_visitor_beacon_does_not_fall_back_to_signed_in_denominator(database):
    repo = PostgresAccountVisitRepository(database)
    repo.record(user(database, MIDNIGHT - timedelta(days=1)), now=MIDNIGHT)
    row = repo.stats(1, now=MIDNIGHT)["days"][0]
    assert row["returning_users"] == 1
    assert row["total_visitors"] == 0
    assert row["return_rate"] is None
    assert row["registration_rate"] is None


@pytest.mark.parametrize(("visitors", "returning", "new", "return_rate", "registration_rate"), [
    (453, 9, 96, 9 / 357, 96 / 444),
    (10, 0, 0, 0, 0),
    (0, 0, 0, None, None),
    (3, 0, 3, None, 1),
    (3, 3, 0, 1, None),
    (1, 0, 2, None, 2),
    (1, 2, 0, 2, None),
    (0, 1, 1, None, None),
])
def test_adjusted_daily_rates_and_nonpositive_denominators(database, visitors, returning, new,
                                                         return_rate, registration_rate):
    day = "2026-10-12"
    visitor_count(database, day, visitors)
    with database.transaction() as conn:
        # Persisted daily facts survive account deletion and count each account once.
        conn.execute(
            """INSERT INTO account_visit_days (day, user_id, is_returning, first_seen_at)
               SELECT %s, id, id <= %s, %s FROM generate_series(1, %s) AS id""",
            (day, returning, MIDNIGHT + timedelta(days=2), returning + new),
        )
    repo = PostgresAccountVisitRepository(database)
    row = repo.stats(2, now=MIDNIGHT + timedelta(days=3))["days"][1]
    assert row == {
        "day": day, "coverage": "complete", "total_visitors": visitors,
        "active_users": returning + new, "returning_users": returning, "new_users": new,
        "return_rate": return_rate, "registration_rate": registration_rate,
    }


def test_registration_rate_counts_only_new_accounts_with_recorded_web_visits(database):
    repo = PostgresAccountVisitRepository(database)
    user(database, MIDNIGHT)  # Registration without a web visit is outside this estimate.
    visitor_count(database, "2026-10-10", 10)
    repo.record(user(database, MIDNIGHT), now=MIDNIGHT)
    row = repo.stats(1, now=MIDNIGHT)["days"][0]
    assert row["new_users"] == 1
    assert row["registration_rate"] == .1


def test_email_check_lease_is_exclusive_and_restart_retains_state(database):
    one, two = PostgresEmailMonitorRepository(database), PostgresEmailMonitorRepository(database)
    token = str(uuid4())
    assert one.claim(token)
    assert not two.claim(str(uuid4()))
    state = {"checked_at": datetime.now(timezone.utc).isoformat(), "alerts": [{"id": "incident"}]}
    one.save(token, state)
    assert two.read()["alerts"] == state["alerts"]
    with pytest.raises(RuntimeError):
        two.save(str(uuid4()), {})
    one.release(token, succeeded=True)
    assert not two.claim(str(uuid4()))  # all workers share the five-minute interval
    with database.transaction() as conn:
        conn.execute("UPDATE email_monitor_state SET next_check_at = CURRENT_TIMESTAMP - INTERVAL '1 second'")
    assert two.claim(str(uuid4()))


def test_email_send_stats_cover_otp_and_briefing_without_content(database):
    repo = PostgresEmailMonitorRepository(database)
    repo.record_event("otp", "accepted", None)
    repo.record_event("briefing", "accepted", None)
    repo.record_event("briefing", "failed", "SMTPConnectError")
    assert repo.delivery_stats() == {"accepted_24h": 2, "failed_24h": 1, "failed_15m": 1}
