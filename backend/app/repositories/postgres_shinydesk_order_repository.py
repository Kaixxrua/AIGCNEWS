"""shinydesk_orders 的 PostgreSQL 实现（迁移 0100）。

条件更新语义与 shinydesk_order_repository.InMemoryShinyDeskOrderRepository 一致；
paypal_order_id / paypal_capture_id 的唯一约束冲突收口为 None（不同订单抢同一个
PayPal 单号只可能是伪造或串单，调用方记 error_events）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from psycopg import errors

from backend.app.core.postgres_database import PostgresDatabaseLifecycle
from backend.app.repositories.shinydesk_order_repository import EMAIL_MAX_ATTEMPTS

_PROJECTION = """
    id, order_no, product_code, amount_cents, currency, status, access_token_hash,
    paypal_order_id, paypal_capture_id, payer_email, license_code, license_id,
    email_status, email_attempts, dispute_status, revoke_reason, lookup_failures,
    last_error, client_ip, callback_payload, expires_at, paid_at, fulfilled_at,
    revoked_at, created_at, updated_at
"""
_CALLBACK_PAYLOAD_MAX_CHARS = 8192


class PostgresShinyDeskOrderRepository:
    def __init__(self, database: PostgresDatabaseLifecycle) -> None:
        self._database = database

    def _fetchone(self, query: str, params: tuple[Any, ...]) -> dict[str, Any] | None:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(query, params)
                row = cursor.fetchone()
        return dict(row) if row is not None else None

    def _update_returning(self, query: str, params: tuple[Any, ...]) -> dict[str, Any] | None:
        try:
            return self._fetchone(query + f" RETURNING {_PROJECTION}", params)
        except errors.UniqueViolation:
            return None

    def _execute(self, query: str, params: tuple[Any, ...]) -> None:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(query, params)

    def create_order(
        self,
        *,
        order_no: str,
        product_code: str,
        amount_cents: int,
        currency: str,
        access_token_hash: str,
        client_ip: str,
        expires_at: datetime,
    ) -> dict[str, Any] | None:
        return self._fetchone(
            f"""
            INSERT INTO shinydesk_orders (
                order_no, product_code, amount_cents, currency, access_token_hash,
                client_ip, expires_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING
            RETURNING {_PROJECTION}
            """,
            (order_no, product_code, int(amount_cents), currency, access_token_hash, client_ip[:100], expires_at),
        )

    def get_by_order_no(self, order_no: str) -> dict[str, Any] | None:
        return self._fetchone(f"SELECT {_PROJECTION} FROM shinydesk_orders WHERE order_no = %s", (order_no,))

    def get_by_paypal_order_id(self, paypal_order_id: str) -> dict[str, Any] | None:
        return self._fetchone(
            f"SELECT {_PROJECTION} FROM shinydesk_orders WHERE paypal_order_id = %s", (paypal_order_id,)
        )

    def get_by_capture_id(self, capture_id: str) -> dict[str, Any] | None:
        return self._fetchone(
            f"SELECT {_PROJECTION} FROM shinydesk_orders WHERE paypal_capture_id = %s", (capture_id,)
        )

    def bind_paypal_order(self, *, order_id: int, paypal_order_id: str) -> dict[str, Any] | None:
        return self._update_returning(
            """
            UPDATE shinydesk_orders
            SET paypal_order_id = %s, updated_at = CURRENT_TIMESTAMP
            WHERE id = %s AND (paypal_order_id IS NULL OR paypal_order_id = %s)
            """,
            (paypal_order_id, int(order_id), paypal_order_id),
        )

    def mark_paid(
        self,
        *,
        order_id: int,
        paypal_order_id: str,
        capture_id: str,
        payer_email: str,
        paid_at: datetime,
        callback_payload: str,
    ) -> dict[str, Any] | None:
        return self._update_returning(
            """
            UPDATE shinydesk_orders
            SET status = 'paid', paypal_order_id = %s, paypal_capture_id = %s,
                payer_email = %s, paid_at = %s, callback_payload = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s AND status = 'pending'
              AND (paypal_order_id IS NULL OR paypal_order_id = %s)
            """,
            (
                paypal_order_id,
                capture_id,
                payer_email[:320],
                paid_at,
                callback_payload[:_CALLBACK_PAYLOAD_MAX_CHARS],
                int(order_id),
                paypal_order_id,
            ),
        )

    def mark_fulfilled(self, *, order_id: int, license_code: str, license_id: str) -> dict[str, Any] | None:
        return self._update_returning(
            """
            UPDATE shinydesk_orders
            SET status = 'fulfilled', license_code = %s, license_id = %s,
                fulfilled_at = CURRENT_TIMESTAMP, last_error = '', updated_at = CURRENT_TIMESTAMP
            WHERE id = %s AND status = 'paid'
            """,
            (license_code, license_id, int(order_id)),
        )

    def record_error(self, *, order_id: int, error: str) -> None:
        self._execute(
            "UPDATE shinydesk_orders SET last_error = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s",
            (error[:500], int(order_id)),
        )

    def claim_email(self, *, order_id: int) -> dict[str, Any] | None:
        return self._update_returning(
            """
            UPDATE shinydesk_orders
            SET email_status = 'sending', email_attempts = email_attempts + 1,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s AND status = 'fulfilled' AND email_status IN ('none', 'failed')
              AND email_attempts < %s AND payer_email <> ''
            """,
            (int(order_id), EMAIL_MAX_ATTEMPTS),
        )

    def finish_email(self, *, order_id: int, status: str) -> None:
        self._execute(
            "UPDATE shinydesk_orders SET email_status = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s",
            (status, int(order_id)),
        )

    def reset_email(self, *, order_id: int) -> None:
        self._execute(
            """
            UPDATE shinydesk_orders SET email_status = 'none', email_attempts = 0,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
            """,
            (int(order_id),),
        )

    def mark_revoked(self, *, order_id: int, reason: str) -> dict[str, Any] | None:
        return self._update_returning(
            """
            UPDATE shinydesk_orders
            SET status = 'revoked', revoke_reason = %s, revoked_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s AND status IN ('paid', 'fulfilled')
            """,
            (reason, int(order_id)),
        )

    def set_dispute_status(self, *, order_id: int, dispute_status: str) -> None:
        self._execute(
            "UPDATE shinydesk_orders SET dispute_status = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s",
            (dispute_status[:60], int(order_id)),
        )

    def record_lookup_failure(self, *, order_id: int) -> None:
        self._execute(
            """
            UPDATE shinydesk_orders SET lookup_failures = LEAST(lookup_failures + 1, 32767)
            WHERE id = %s
            """,
            (int(order_id),),
        )

    def list_orders(self, *, query: str, page: int, page_size: int) -> tuple[list[dict[str, Any]], int]:
        needle = query.strip()
        where = "TRUE"
        params: list[Any] = []
        if needle:
            where = (
                "(order_no = %s OR paypal_order_id = %s OR paypal_capture_id = %s"
                " OR lower(payer_email) = lower(%s))"
            )
            params = [needle, needle, needle, needle]
        offset = (max(1, page) - 1) * page_size
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(f"SELECT COUNT(*) AS cnt FROM shinydesk_orders WHERE {where}", tuple(params))
                total = int(cursor.fetchone()["cnt"])
                cursor.execute(
                    f"""
                    SELECT {_PROJECTION} FROM shinydesk_orders WHERE {where}
                    ORDER BY id DESC LIMIT %s OFFSET %s
                    """,
                    (*params, page_size, offset),
                )
                rows = [dict(row) for row in cursor.fetchall()]
        return rows, total
