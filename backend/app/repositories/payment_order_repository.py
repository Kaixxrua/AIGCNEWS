"""支付订单持久化边界（ADR 0002）。

行契约是 ``dict[str, Any]``（无 ORM、无行模型，与既有仓储一致）。
状态机常量由 services/payments/orders.py 持有，仓储层不做枚举校验，
只做条件更新（条件不满足 = rowcount 0 = 幂等 no-op）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol


class PaymentOrderWriter(Protocol):
    """Create orders and run the conditional state transitions."""

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
        """Insert a pending order; returns the row, or None when either unique
        index (order_no / (user_id, idempotency_key)) rejected the insert —
        caller re-reads the existing row by idempotency key or retries."""
        ...

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
        """恰好一次发放闸门：单事务内条件 UPDATE 订单为 paid（仅 pending/
        expired 可转入；重放/并发命中 rowcount=0 时返回 None 且零写入），
        随后同事务写入用户会员档位与到期时间。"""
        ...

    def close_order(self, *, order_id: int) -> dict[str, Any] | None:
        """pending → closed；任何其他状态返回 None（终态幂等/冲突由路由映射）。"""
        ...

    def mark_expired_overdue(self, *, now: datetime, limit: int) -> int:
        """超时关单扫描：pending 且 expires_at <= now 的订单批量转 expired，
        返回影响行数（调度任务每批 capped by limit）。"""
        ...


class PaymentOrderReader(Protocol):
    """Read projections consumed by user-facing payment routes."""

    def get_order_by_order_no(self, order_no: str) -> dict[str, Any] | None: ...

    def get_order_by_user_and_idempotency_key(
        self,
        *,
        user_id: int,
        idempotency_key: str,
    ) -> dict[str, Any] | None: ...

    def list_user_orders(
        self,
        *,
        user_id: int,
        page: int,
        page_size: int,
    ) -> tuple[list[dict[str, Any]], int]:
        """我的订单（id DESC 新到旧）+ 总数，供分页。"""
        ...


class PaymentOrderAdminReader(Protocol):
    """Read projections consumed by ops payment routes (may join users)."""

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
        """台账筛选（行内含 users.email 列）+ 总数。"""
        ...


class PaymentOrderRepository(
    PaymentOrderReader,
    PaymentOrderWriter,
    PaymentOrderAdminReader,
    Protocol,
):
    """Combined payment-order persistence boundary."""
