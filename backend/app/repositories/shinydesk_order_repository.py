"""shinydesk_orders 仓储协议与进程内实现（测试、本地联调用）。

PostgreSQL 实现见 postgres_shinydesk_order_repository.py；两者条件更新语义一致：
- mark_paid 只接 pending（且 PayPal 订单号未绑定或一致）；
- mark_fulfilled 只接 paid；mark_revoked 只接 paid/fulfilled；
- claim_email 只接 fulfilled 且未发成功、尝试 < 3 次。
返回 None 一律表示前提不满足（重放/并发/人工已处理），调用方回读后按现状应答。
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any, Protocol

EMAIL_MAX_ATTEMPTS = 3


class ShinyDeskOrderRepository(Protocol):
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
    ) -> dict[str, Any] | None: ...

    def get_by_order_no(self, order_no: str) -> dict[str, Any] | None: ...

    def get_by_paypal_order_id(self, paypal_order_id: str) -> dict[str, Any] | None: ...

    def get_by_capture_id(self, capture_id: str) -> dict[str, Any] | None: ...

    def bind_paypal_order(self, *, order_id: int, paypal_order_id: str) -> dict[str, Any] | None: ...

    def mark_paid(
        self,
        *,
        order_id: int,
        paypal_order_id: str,
        capture_id: str,
        payer_email: str,
        paid_at: datetime,
        callback_payload: str,
    ) -> dict[str, Any] | None: ...

    def mark_fulfilled(self, *, order_id: int, license_code: str, license_id: str) -> dict[str, Any] | None: ...

    def record_error(self, *, order_id: int, error: str) -> None: ...

    def claim_email(self, *, order_id: int) -> dict[str, Any] | None: ...

    def finish_email(self, *, order_id: int, status: str) -> None: ...

    def reset_email(self, *, order_id: int) -> None: ...

    def mark_revoked(self, *, order_id: int, reason: str) -> dict[str, Any] | None: ...

    def set_dispute_status(self, *, order_id: int, dispute_status: str) -> None: ...

    def record_lookup_failure(self, *, order_id: int) -> None: ...

    def list_orders(self, *, query: str, page: int, page_size: int) -> tuple[list[dict[str, Any]], int]: ...


def _now() -> datetime:
    return datetime.now(timezone.utc)


class InMemoryShinyDeskOrderRepository:
    """线程安全的进程内实现；唯一约束与条件更新与 PG 实现同语义。"""

    def __init__(self) -> None:
        self._rows: dict[int, dict[str, Any]] = {}
        self._next_id = 1
        self._lock = threading.Lock()

    def _find(self, key: str, value: object) -> dict[str, Any] | None:
        for row in self._rows.values():
            if row[key] == value:
                return row
        return None

    def _update(self, order_id: int, **changes: Any) -> dict[str, Any]:
        row = self._rows[order_id]
        row.update(changes, updated_at=_now())
        return dict(row)

    def create_order(self, **kwargs: Any) -> dict[str, Any] | None:
        with self._lock:
            if self._find("order_no", kwargs["order_no"]) is not None:
                return None
            now = _now()
            row = {
                "id": self._next_id,
                **kwargs,
                "status": "pending",
                "paypal_order_id": None,
                "paypal_capture_id": None,
                "payer_email": "",
                "license_code": "",
                "license_id": "",
                "email_status": "none",
                "email_attempts": 0,
                "dispute_status": "",
                "revoke_reason": "",
                "lookup_failures": 0,
                "last_error": "",
                "callback_payload": "",
                "paid_at": None,
                "fulfilled_at": None,
                "revoked_at": None,
                "created_at": now,
                "updated_at": now,
            }
            self._rows[row["id"]] = row
            self._next_id += 1
            return dict(row)

    def get_by_order_no(self, order_no: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._find("order_no", order_no)
            return dict(row) if row else None

    def get_by_paypal_order_id(self, paypal_order_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._find("paypal_order_id", paypal_order_id)
            return dict(row) if row else None

    def get_by_capture_id(self, capture_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._find("paypal_capture_id", capture_id)
            return dict(row) if row else None

    def bind_paypal_order(self, *, order_id: int, paypal_order_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._rows.get(order_id)
            if row is None:
                return None
            other = self._find("paypal_order_id", paypal_order_id)
            if other is not None and other["id"] != order_id:
                return None
            if row["paypal_order_id"] not in (None, paypal_order_id):
                return None
            return self._update(order_id, paypal_order_id=paypal_order_id)

    def mark_paid(self, *, order_id: int, **kwargs: Any) -> dict[str, Any] | None:
        with self._lock:
            row = self._rows.get(order_id)
            if row is None or row["status"] != "pending":
                return None
            if row["paypal_order_id"] not in (None, kwargs["paypal_order_id"]):
                return None
            capture_owner = self._find("paypal_capture_id", kwargs["capture_id"])
            if capture_owner is not None and capture_owner["id"] != order_id:
                return None
            return self._update(
                order_id,
                status="paid",
                paypal_order_id=kwargs["paypal_order_id"],
                paypal_capture_id=kwargs["capture_id"],
                payer_email=kwargs["payer_email"],
                paid_at=kwargs["paid_at"],
                callback_payload=kwargs["callback_payload"][:8192],
            )

    def mark_fulfilled(self, *, order_id: int, license_code: str, license_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._rows.get(order_id)
            if row is None or row["status"] != "paid":
                return None
            return self._update(
                order_id,
                status="fulfilled",
                license_code=license_code,
                license_id=license_id,
                fulfilled_at=_now(),
                last_error="",
            )

    def record_error(self, *, order_id: int, error: str) -> None:
        with self._lock:
            if order_id in self._rows:
                self._update(order_id, last_error=error[:500])

    def claim_email(self, *, order_id: int) -> dict[str, Any] | None:
        with self._lock:
            row = self._rows.get(order_id)
            if (
                row is None
                or row["status"] != "fulfilled"
                or row["email_status"] not in ("none", "failed")
                or row["email_attempts"] >= EMAIL_MAX_ATTEMPTS
                or not row["payer_email"]
            ):
                return None
            return self._update(order_id, email_status="sending", email_attempts=row["email_attempts"] + 1)

    def finish_email(self, *, order_id: int, status: str) -> None:
        with self._lock:
            if order_id in self._rows:
                self._update(order_id, email_status=status)

    def reset_email(self, *, order_id: int) -> None:
        with self._lock:
            if order_id in self._rows:
                self._update(order_id, email_status="none", email_attempts=0)

    def mark_revoked(self, *, order_id: int, reason: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._rows.get(order_id)
            if row is None or row["status"] not in ("paid", "fulfilled"):
                return None
            return self._update(order_id, status="revoked", revoke_reason=reason, revoked_at=_now())

    def set_dispute_status(self, *, order_id: int, dispute_status: str) -> None:
        with self._lock:
            if order_id in self._rows:
                self._update(order_id, dispute_status=dispute_status[:60])

    def record_lookup_failure(self, *, order_id: int) -> None:
        with self._lock:
            row = self._rows.get(order_id)
            if row is not None:
                self._update(order_id, lookup_failures=min(row["lookup_failures"] + 1, 32767))

    def list_orders(self, *, query: str, page: int, page_size: int) -> tuple[list[dict[str, Any]], int]:
        with self._lock:
            needle = query.strip().lower()
            rows = [
                dict(row)
                for row in self._rows.values()
                if not needle
                or needle
                in (
                    row["order_no"].lower(),
                    (row["paypal_order_id"] or "").lower(),
                    (row["paypal_capture_id"] or "").lower(),
                    row["payer_email"].lower(),
                )
            ]
            rows.sort(key=lambda row: row["id"], reverse=True)
            start = (max(1, page) - 1) * page_size
            return rows[start : start + page_size], len(rows)
