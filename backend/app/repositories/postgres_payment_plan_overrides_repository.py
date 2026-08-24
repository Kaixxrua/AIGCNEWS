from __future__ import annotations

from typing import Any

from backend.app.core.postgres_database import PostgresDatabaseLifecycle
from backend.app.repositories.payment_plan_overrides_repository import PaymentPlanOverride

_COLUMNS = "plan_code, amount_cents, updated_at"
_MIN_AMOUNT_CENTS = 100
_MAX_AMOUNT_CENTS = 1000000


class PostgresPaymentPlanOverridesRepository:
    """PostgreSQL persistence for runtime membership plan price overrides."""

    def __init__(self, database: PostgresDatabaseLifecycle) -> None:
        self._database = database

    def list_plan_overrides(self) -> tuple[PaymentPlanOverride, ...]:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(f"SELECT {_COLUMNS} FROM payment_plan_overrides ORDER BY plan_code")
                return tuple(self._row_to_override(row) for row in cursor.fetchall())

    def upsert_plan_override(self, *, plan_code: str, amount_cents: int) -> PaymentPlanOverride:
        cents = int(amount_cents)
        if not _MIN_AMOUNT_CENTS <= cents <= _MAX_AMOUNT_CENTS:
            raise ValueError("套餐价格必须是 100-1000000 之间的整数分")
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    INSERT INTO payment_plan_overrides (plan_code, amount_cents, updated_at)
                    VALUES (%s, %s, CURRENT_TIMESTAMP)
                    ON CONFLICT (plan_code) DO UPDATE SET
                        amount_cents = EXCLUDED.amount_cents,
                        updated_at = CURRENT_TIMESTAMP
                    RETURNING {_COLUMNS}
                    """,
                    (plan_code, cents),
                )
                row = cursor.fetchone()
        return self._row_to_override(row)

    def delete_plan_override(self, plan_code: str) -> int:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM payment_plan_overrides WHERE plan_code = %s", (plan_code,))
                return int(cursor.rowcount)

    @staticmethod
    def _row_to_override(row: dict[str, Any]) -> PaymentPlanOverride:
        return PaymentPlanOverride(
            plan_code=str(row["plan_code"]),
            amount_cents=int(row["amount_cents"]),
            updated_at=row["updated_at"],
        )
