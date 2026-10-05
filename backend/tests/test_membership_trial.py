"""会员试用（每个账号一次、7 天）：状态判定、PostgreSQL 仓储与路由。"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api import routes_membership
from backend.app.api.routes_membership import get_membership_trial_repository
from backend.app.core.auth import RequireUser
from backend.app.repositories.membership_trial_repository import (
    MembershipTrialRepository,
    TrialStartResult,
)
from backend.app.repositories.postgres_membership_trial_repository import (
    PostgresMembershipTrialRepository,
)
from backend.app.services.membership.trial import (
    TRIAL_DAYS,
    TrialRecord,
    TrialSnapshot,
    trial_status,
)

NOW = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)
TRIAL_END = NOW + timedelta(days=7)


def _trial(start: datetime = NOW) -> TrialRecord:
    return TrialRecord(started_at=start, expires_at=start + timedelta(days=TRIAL_DAYS))


# ---------------------------------------------------------------- 状态判定


def test_trial_is_seven_days() -> None:
    assert TRIAL_DAYS == 7


def test_free_user_without_trial_can_start() -> None:
    status = trial_status(TrialSnapshot("free", None, None), now=NOW)

    assert status == {
        "days": 7,
        "available": True,
        "active": False,
        "started_at": None,
        "expires_at": None,
    }


def test_effective_members_cannot_start() -> None:
    permanent = TrialSnapshot("member", None, None)
    paid = TrialSnapshot("member", NOW + timedelta(days=30), None)

    for snapshot in (permanent, paid):
        status = trial_status(snapshot, now=NOW)
        assert status["available"] is False
        assert status["active"] is False


def test_lapsed_member_without_trial_can_start() -> None:
    status = trial_status(TrialSnapshot("member", NOW - timedelta(seconds=1), None), now=NOW)

    assert status["available"] is True


def test_unknown_tier_counts_as_free() -> None:
    assert trial_status(TrialSnapshot("vip", None, None), now=NOW)["available"] is True


def test_running_trial_is_active_and_not_available_again() -> None:
    status = trial_status(TrialSnapshot("member", TRIAL_END, _trial()), now=NOW + timedelta(days=3))

    assert status == {
        "days": 7,
        "available": False,
        "active": True,
        "started_at": NOW.isoformat(),
        "expires_at": TRIAL_END.isoformat(),
    }


def test_finished_trial_is_neither_active_nor_available() -> None:
    status = trial_status(TrialSnapshot("member", TRIAL_END, _trial()), now=TRIAL_END)

    assert status["available"] is False
    assert status["active"] is False
    assert status["expires_at"] == TRIAL_END.isoformat()


def test_paying_during_trial_ends_trial_display() -> None:
    # 付费叠加在试用到期日之后，到期时间不再是试用写下的值
    paid_through = TRIAL_END + timedelta(days=30)
    status = trial_status(TrialSnapshot("member", paid_through, _trial()), now=NOW + timedelta(days=1))

    assert status["active"] is False
    assert status["available"] is False


def test_ops_downgrade_during_trial_ends_trial_display() -> None:
    status = trial_status(TrialSnapshot("free", TRIAL_END, _trial()), now=NOW + timedelta(days=1))

    assert status["active"] is False
    assert status["available"] is False


def test_naive_timestamps_are_read_as_utc() -> None:
    naive_start = NOW.replace(tzinfo=None)
    record = TrialRecord(started_at=naive_start, expires_at=naive_start + timedelta(days=7))
    status = trial_status(TrialSnapshot("member", TRIAL_END, record), now=NOW)

    assert status["active"] is True
    assert status["started_at"] == NOW.isoformat()


# ---------------------------------------------------------------- PostgreSQL 仓储


class FakeDatabase:
    def __init__(self, cursor: MagicMock) -> None:
        self.cursor = cursor
        self.connection = MagicMock()
        cursor_context = MagicMock()
        cursor_context.__enter__.return_value = cursor
        self.connection.cursor.return_value = cursor_context
        self.transaction_count = 0

    @contextmanager
    def transaction(self):
        self.transaction_count += 1
        yield self.connection


def _make_repository(*rows: Any):
    cursor = MagicMock()
    cursor.fetchone.side_effect = list(rows)
    database = FakeDatabase(cursor)
    return PostgresMembershipTrialRepository(database), database, cursor


def _statements(cursor: MagicMock) -> list[str]:
    return [" ".join(call.args[0].split()) for call in cursor.execute.call_args_list]


def _writes(cursor: MagicMock) -> list[str]:
    """写语句（INSERT/UPDATE 开头）；SELECT ... FOR UPDATE 不算。"""
    return [sql for sql in _statements(cursor) if sql.startswith(("INSERT", "UPDATE"))]


def test_adapter_exposes_trial_repository_contract() -> None:
    repository, _, _ = _make_repository()
    contract: MembershipTrialRepository = repository

    assert callable(contract.get_trial_snapshot)
    assert callable(contract.start_trial)


def test_snapshot_joins_trial_row() -> None:
    repository, _, cursor = _make_repository(
        {
            "membership_tier": "member",
            "membership_expires_at": TRIAL_END,
            "started_at": NOW,
            "trial_expires_at": TRIAL_END,
        }
    )

    snapshot = repository.get_trial_snapshot(7)

    assert snapshot == TrialSnapshot("member", TRIAL_END, TrialRecord(NOW, TRIAL_END))
    sql = _statements(cursor)[0]
    assert "LEFT JOIN membership_trials t ON t.user_id = u.id" in sql
    assert cursor.execute.call_args.args[1] == (7,)


def test_snapshot_without_trial_row() -> None:
    repository, _, _ = _make_repository(
        {
            "membership_tier": "free",
            "membership_expires_at": None,
            "started_at": None,
            "trial_expires_at": None,
        }
    )

    assert repository.get_trial_snapshot(7) == TrialSnapshot("free", None, None)


def test_snapshot_missing_user() -> None:
    repository, _, _ = _make_repository(None)

    assert repository.get_trial_snapshot(7) is None


def test_start_trial_locks_user_then_inserts_and_grants_in_one_transaction() -> None:
    repository, database, cursor = _make_repository(
        {"membership_tier": "free", "membership_expires_at": None},
        None,
        {"started_at": NOW, "expires_at": TRIAL_END},
    )

    result = repository.start_trial(user_id=7, now=NOW)

    assert result == TrialStartResult(
        outcome="started",
        snapshot=TrialSnapshot("member", TRIAL_END, TrialRecord(NOW, TRIAL_END)),
    )
    assert database.transaction_count == 1
    statements = _statements(cursor)
    assert len(statements) == 4
    assert statements[0].endswith("WHERE id = %s FOR UPDATE")
    assert "FROM membership_trials WHERE user_id = %s" in statements[1]
    assert "INSERT INTO membership_trials" in statements[2]
    assert "ON CONFLICT (user_id) DO NOTHING" in statements[2]
    assert cursor.execute.call_args_list[2].args[1] == (7, NOW, TRIAL_END)
    assert statements[3].startswith("UPDATE users SET membership_tier = %s, membership_expires_at = %s")
    assert cursor.execute.call_args_list[3].args[1] == ("member", TRIAL_END, 7)


def test_lapsed_member_can_start_trial() -> None:
    repository, _, cursor = _make_repository(
        {"membership_tier": "member", "membership_expires_at": NOW - timedelta(days=1)},
        None,
        {"started_at": NOW, "expires_at": TRIAL_END},
    )

    assert repository.start_trial(user_id=7, now=NOW).outcome == "started"
    assert cursor.execute.call_args_list[3].args[1] == ("member", TRIAL_END, 7)


def test_start_trial_refuses_second_trial_without_writing() -> None:
    previous = TrialRecord(NOW - timedelta(days=30), NOW - timedelta(days=23))
    repository, _, cursor = _make_repository(
        {"membership_tier": "member", "membership_expires_at": previous.expires_at},
        {"started_at": previous.started_at, "expires_at": previous.expires_at},
    )

    result = repository.start_trial(user_id=7, now=NOW)

    assert result.outcome == "already_used"
    assert result.snapshot == TrialSnapshot("member", previous.expires_at, previous)
    assert _writes(cursor) == []


def test_start_trial_refuses_effective_member_without_writing() -> None:
    for expires_at in (None, NOW + timedelta(days=30)):
        repository, _, cursor = _make_repository(
            {"membership_tier": "member", "membership_expires_at": expires_at},
            None,
        )

        result = repository.start_trial(user_id=7, now=NOW)

        assert result.outcome == "already_member"
        assert result.snapshot == TrialSnapshot("member", expires_at, None)
        assert _writes(cursor) == []


def test_start_trial_missing_user() -> None:
    repository, _, cursor = _make_repository(None)

    assert repository.start_trial(user_id=7, now=NOW) == TrialStartResult(outcome="user_missing", snapshot=None)
    assert len(_statements(cursor)) == 1


def test_insert_conflict_does_not_grant() -> None:
    repository, _, cursor = _make_repository(
        {"membership_tier": "free", "membership_expires_at": None},
        None,
        None,
    )

    assert repository.start_trial(user_id=7, now=NOW).outcome == "already_used"
    assert [sql.split(" (")[0] for sql in _writes(cursor)] == ["INSERT INTO membership_trials"]


# ---------------------------------------------------------------- 路由


class FakeTrials:
    def __init__(
        self,
        snapshot: TrialSnapshot | None = None,
        start: TrialStartResult | None = None,
    ) -> None:
        self.snapshot = snapshot
        self.start = start
        self.calls: list[tuple[str, Any]] = []

    def get_trial_snapshot(self, user_id: int) -> TrialSnapshot | None:
        self.calls.append(("get", user_id))
        return self.snapshot

    def start_trial(self, *, user_id: int, now: datetime) -> TrialStartResult:
        self.calls.append(("start", (user_id, now)))
        assert self.start is not None
        return self.start


def _client(trials: FakeTrials, *, user: dict[str, Any] | None = None) -> TestClient:
    app = FastAPI()
    app.include_router(routes_membership.router, prefix="/api")
    app.dependency_overrides[get_membership_trial_repository] = lambda: trials
    if user is not None:
        app.dependency_overrides[RequireUser] = lambda: user
    return TestClient(app)


def test_get_status_for_signed_in_user() -> None:
    trials = FakeTrials(snapshot=TrialSnapshot("free", None, None))

    response = _client(trials, user={"user_id": 7}).get("/api/membership/trial")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "days": 7,
        "available": True,
        "active": False,
        "started_at": None,
        "expires_at": None,
    }
    assert trials.calls == [("get", 7)]


def test_endpoints_require_sign_in() -> None:
    client = _client(FakeTrials())

    assert client.get("/api/membership/trial").status_code == 401
    assert client.post("/api/membership/trial").status_code == 401


def test_get_status_for_deleted_user_is_unauthorized() -> None:
    response = _client(FakeTrials(snapshot=None), user={"user_id": 7}).get("/api/membership/trial")

    assert response.status_code == 401


def test_start_returns_active_trial() -> None:
    started = TrialStartResult(
        outcome="started",
        snapshot=TrialSnapshot("member", TRIAL_END, TrialRecord(NOW, TRIAL_END)),
    )
    trials = FakeTrials(start=started)

    before = datetime.now(timezone.utc)
    response = _client(trials, user={"user_id": 7}).post("/api/membership/trial")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["expires_at"] == TRIAL_END.isoformat()
    assert body["available"] is False
    ((kind, (user_id, now)),) = trials.calls
    assert (kind, user_id) == ("start", 7)
    assert now.tzinfo is not None and now >= before


def test_start_conflicts_map_to_detail_codes() -> None:
    for outcome, detail in (
        ("already_used", "trial_already_used"),
        ("already_member", "already_member"),
    ):
        trials = FakeTrials(start=TrialStartResult(outcome=outcome, snapshot=TrialSnapshot("free", None, None)))

        response = _client(trials, user={"user_id": 7}).post("/api/membership/trial")

        assert response.status_code == 409
        assert response.json() == {"detail": detail}


def test_start_for_deleted_user_is_unauthorized() -> None:
    trials = FakeTrials(start=TrialStartResult(outcome="user_missing", snapshot=None))

    response = _client(trials, user={"user_id": 7}).post("/api/membership/trial")

    assert response.status_code == 401


def test_main_app_mounts_trial_routes() -> None:
    from backend.app.main import app

    operations = app.openapi()["paths"]["/api/membership/trial"]
    assert {"get", "post"} <= set(operations)
