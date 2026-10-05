from __future__ import annotations

from datetime import datetime
from typing import Any

from backend.app.core.postgres_database import PostgresDatabaseLifecycle
from backend.app.domain.membership import MEMBERSHIP_TIER_MEMBER
from backend.app.domain.membership_trial import (
    TrialRecord,
    TrialSnapshot,
    is_effective_member,
    trial_expiry,
)
from backend.app.repositories.membership_trial_repository import TrialStartResult


def _snapshot(user: dict[str, Any], trial: TrialRecord | None) -> TrialSnapshot:
    return TrialSnapshot(
        membership_tier=user.get("membership_tier"),
        membership_expires_at=user.get("membership_expires_at"),
        trial=trial,
    )


class PostgresMembershipTrialRepository:
    """会员试用的 PostgreSQL 持久化：每个账号一次，开通与会员列同事务写入。"""

    def __init__(self, database: PostgresDatabaseLifecycle) -> None:
        self._database = database

    def get_trial_snapshot(self, user_id: int) -> TrialSnapshot | None:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT u.membership_tier, u.membership_expires_at,
                           t.started_at, t.expires_at AS trial_expires_at
                    FROM users u
                    LEFT JOIN membership_trials t ON t.user_id = u.id
                    WHERE u.id = %s
                    """,
                    (int(user_id),),
                )
                row = cursor.fetchone()
        if row is None:
            return None
        trial = (
            TrialRecord(started_at=row["started_at"], expires_at=row["trial_expires_at"])
            if row.get("started_at") is not None
            else None
        )
        return _snapshot(row, trial)

    def start_trial(self, *, user_id: int, now: datetime) -> TrialStartResult:
        """锁住用户行后判定并开通：用过试用或眼下是有效会员都不写任何东西。

        行锁让同一账号的并发开通排队：后到的请求看到已写下的试用记录，回
        already_used；与付费开通（payment_orders 条件更新 users）也按行锁串行。
        """
        expires_at = trial_expiry(now)
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT membership_tier, membership_expires_at
                    FROM users
                    WHERE id = %s
                    FOR UPDATE
                    """,
                    (int(user_id),),
                )
                user = cursor.fetchone()
                if user is None:
                    return TrialStartResult(outcome="user_missing", snapshot=None)
                cursor.execute(
                    "SELECT started_at, expires_at FROM membership_trials WHERE user_id = %s",
                    (int(user_id),),
                )
                existing = cursor.fetchone()
                if existing is not None:
                    record = TrialRecord(
                        started_at=existing["started_at"], expires_at=existing["expires_at"]
                    )
                    return TrialStartResult(outcome="already_used", snapshot=_snapshot(user, record))
                current = _snapshot(user, None)
                if is_effective_member(current, now=now):
                    return TrialStartResult(outcome="already_member", snapshot=current)
                cursor.execute(
                    """
                    INSERT INTO membership_trials (user_id, started_at, expires_at)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (user_id) DO NOTHING
                    RETURNING started_at, expires_at
                    """,
                    (int(user_id), now, expires_at),
                )
                inserted = cursor.fetchone()
                if inserted is None:
                    # 行锁下不应发生；防御性按「用过」处理，不改会员列
                    return TrialStartResult(outcome="already_used", snapshot=current)
                cursor.execute(
                    """
                    UPDATE users
                    SET membership_tier = %s, membership_expires_at = %s
                    WHERE id = %s
                    """,
                    (MEMBERSHIP_TIER_MEMBER, expires_at, int(user_id)),
                )
        record = TrialRecord(started_at=inserted["started_at"], expires_at=inserted["expires_at"])
        return TrialStartResult(
            outcome="started",
            snapshot=TrialSnapshot(
                membership_tier=MEMBERSHIP_TIER_MEMBER,
                membership_expires_at=inserted["expires_at"],
                trial=record,
            ),
        )
