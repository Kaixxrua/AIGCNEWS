"""payment_orders 的 PostgreSQL 实现（ADR 0002）。

恰好一次发放由 ``mark_paid_and_grant`` 的条件 UPDATE 承载：渠道重发、
并发双回调、Ops 重复补单全部在 rowcount=0 处收口为幂等 no-op；用户会员
档位与订单写在同一事务，无"已收款未发放"的崩溃窗口。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from backend.app.core.postgres_database import PostgresDatabaseLifecycle

_ORDER_PROJECTION = """
    id, order_no, user_id, plan_code, channel, amount_cents, currency,
    status, channel_order_no, idempotency_key, callback_payload,
    paid_at, grant_expires_at, expires_at, created_at, updated_at
"""

# 回调原始报文审计列的截断上限（防御异常大的渠道报文撑爆行宽）
_CALLBACK_PAYLOAD_MAX_CHARS = 8192


class PostgresPaymentOrderRepository:
    """PostgreSQL persistence for membership payment orders."""

    def __init__(self, database: PostgresDatabaseLifecycle) -> None:
        self._database = database

    def create_order(
        self,
        *,
        order_no: str,
        user_id: int,
        plan_code: str,
        channel: str,
        amount_cents: int,
        currency: str,
        idempotency_key: str,
        expires_at: datetime,
    ) -> dict[str, Any] | None:
        # ON CONFLICT DO NOTHING 同时盖住 order_no 与部分唯一幂等键两个
        # 冲突面：冲突即返回 None，由调用方按幂等键回读既有单或换号重试。
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO payment_orders (
                        order_no, user_id, plan_code, channel, amount_cents,
                        currency, idempotency_key, expires_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT DO NOTHING
                    RETURNING id
                    """,
                    (
                        order_no,
                        int(user_id),
                        plan_code,
                        channel,
                        int(amount_cents),
                        currency,
                        idempotency_key,
                        expires_at,
                    ),
                )
                row = cursor.fetchone()
                if row is None:
                    return None
        return self.get_order_by_order_no(order_no)

    def get_order_by_order_no(self, order_no: str) -> dict[str, Any] | None:
        return self._fetchone(
            f"SELECT {_ORDER_PROJECTION} FROM payment_orders WHERE order_no = %s",
            (order_no,),
        )

    def get_order_by_user_and_idempotency_key(
        self,
        *,
        user_id: int,
        idempotency_key: str,
    ) -> dict[str, Any] | None:
        return self._fetchone(
            f"""
            SELECT {_ORDER_PROJECTION}
            FROM payment_orders
            WHERE user_id = %s AND idempotency_key = %s
            """,
            (int(user_id), idempotency_key),
        )

    def list_user_orders(
        self,
        *,
        user_id: int,
        page: int,
        page_size: int,
    ) -> tuple[list[dict[str, Any]], int]:
        offset = (max(1, page) - 1) * page_size
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT COUNT(*) AS cnt FROM payment_orders WHERE user_id = %s",
                    (int(user_id),),
                )
                total = int(cursor.fetchone()["cnt"])
                cursor.execute(
                    f"""
                    SELECT {_ORDER_PROJECTION}
                    FROM payment_orders
                    WHERE user_id = %s
                    ORDER BY id DESC
                    LIMIT %s OFFSET %s
                    """,
                    (int(user_id), page_size, offset),
                )
                items = [dict(row) for row in cursor.fetchall()]
        return items, total

    def get_revenue_stats(
        self,
        *,
        windows: dict[str, tuple[datetime, datetime]],
    ) -> dict[str, dict[str, int]]:
        """Aggregate paid order amounts in cents, preserving currency separation."""
        if not windows:
            return {}
        earliest_start = min(start for start, _ in windows.values())
        latest_end = max(end for _, end in windows.values())
        result = {
            name: {"cny_amount_cents": 0, "usd_amount_cents": 0}
            for name in windows
        }
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT paid_at, currency, amount_cents
                    FROM payment_orders
                    WHERE status = 'paid'
                      AND paid_at IS NOT NULL
                      AND paid_at >= %s
                      AND paid_at < %s
                      AND currency IN ('CNY', 'USD')
                    """,
                    (earliest_start, latest_end),
                )
                rows = cursor.fetchall()
        for row in rows:
            paid_at = row["paid_at"]
            currency = str(row["currency"]).upper()
            amount = int(row["amount_cents"])
            for name, (start, end) in windows.items():
                if start <= paid_at < end:
                    result[name][f"{currency.lower()}_amount_cents"] += amount
        return result

    def list_orders_admin(
        self,
        *,
        status: str | None,
        channel: str | None,
        plan_code: str | None,
        email: str | None,
        created_from: datetime | None,
        created_to: datetime | None,
        page: int,
        page_size: int,
    ) -> tuple[list[dict[str, Any]], int]:
        conditions = ["TRUE"]
        params: list[Any] = []
        if status:
            conditions.append("o.status = %s")
            params.append(status)
        if channel:
            conditions.append("o.channel = %s")
            params.append(channel)
        if plan_code:
            conditions.append("o.plan_code = %s")
            params.append(plan_code)
        if email:
            conditions.append("u.email = %s")
            params.append(email.strip().lower())
        if created_from is not None:
            conditions.append("o.created_at >= %s")
            params.append(created_from)
        if created_to is not None:
            conditions.append("o.created_at <= %s")
            params.append(created_to)
        where_clause = " AND ".join(conditions)
        offset = (max(1, page) - 1) * page_size
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT COUNT(*) AS cnt
                    FROM payment_orders o
                    JOIN users u ON u.id = o.user_id
                    WHERE {where_clause}
                    """,
                    tuple(params),
                )
                total = int(cursor.fetchone()["cnt"])
                cursor.execute(
                    f"""
                    SELECT o.id, o.order_no, o.user_id, o.plan_code, o.channel,
                           o.amount_cents, o.currency, o.status, o.channel_order_no,
                           o.idempotency_key, o.callback_payload, o.paid_at,
                           o.grant_expires_at, o.expires_at, o.created_at,
                           o.updated_at, u.email AS user_email
                    FROM payment_orders o
                    JOIN users u ON u.id = o.user_id
                    WHERE {where_clause}
                    ORDER BY o.id DESC
                    LIMIT %s OFFSET %s
                    """,
                    (*params, page_size, offset),
                )
                items = [dict(row) for row in cursor.fetchall()]
        return items, total

    def mark_paid_and_grant(
        self,
        *,
        order_id: int,
        channel_order_no: str,
        paid_at: datetime,
        callback_payload: str,
        grant_expires_at: datetime | None,
        user_id: int,
        new_membership_tier: str,
        new_membership_expires_at: datetime | None,
    ) -> dict[str, Any] | None:
        # 条件 UPDATE 是恰好一次闸门：只有 pending/expired 能转 paid；
        # 渠道重发、并发双回调、Ops 重复补单全部命中 rowcount=0 → 提前
        # 返回 None，users 更新不执行，事务零写入。
        payload = callback_payload[:_CALLBACK_PAYLOAD_MAX_CHARS]
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    UPDATE payment_orders
                    SET status = 'paid', channel_order_no = %s, paid_at = %s,
                        callback_payload = %s, grant_expires_at = %s,
                        updated_at = now()
                    WHERE id = %s AND status IN ('pending', 'expired')
                    RETURNING {_ORDER_PROJECTION}
                    """,
                    (
                        channel_order_no,
                        paid_at,
                        payload,
                        grant_expires_at,
                        int(order_id),
                    ),
                )
                row = cursor.fetchone()
                if row is None:
                    return None
                cursor.execute(
                    """
                    UPDATE users
                    SET membership_tier = %s, membership_expires_at = %s
                    WHERE id = %s
                    """,
                    (new_membership_tier, new_membership_expires_at, int(user_id)),
                )
                return dict(row)

    def close_order(self, *, order_id: int) -> dict[str, Any] | None:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    UPDATE payment_orders
                    SET status = 'closed', updated_at = now()
                    WHERE id = %s AND status = 'pending'
                    RETURNING {_ORDER_PROJECTION}
                    """,
                    (int(order_id),),
                )
                row = cursor.fetchone()
                return dict(row) if row else None

    def mark_expired_overdue(self, *, now: datetime, limit: int) -> int:
        # 子查询限量 + 主键序，命中 (status, expires_at) 索引；批量上限防
        # 单轮长事务（欠账下轮补齐，任务每 5 分钟跑）。
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE payment_orders
                    SET status = 'expired', updated_at = now()
                    WHERE id IN (
                        SELECT id FROM payment_orders
                        WHERE status = 'pending' AND expires_at <= %s
                        ORDER BY id
                        LIMIT %s
                    )
                    """,
                    (now, int(limit)),
                )
                return int(cursor.rowcount)

    def _fetchone(
        self,
        sql: str,
        params: tuple[Any, ...] = (),
    ) -> dict[str, Any] | None:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql, params)
                row = cursor.fetchone()
                return dict(row) if row else None
