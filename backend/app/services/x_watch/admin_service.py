from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Protocol

from backend.app.repositories.postgres_x_watch_repository import (
    normalize_x_screen_name,
)
from backend.app.repositories.x_watch_repository import XWatchAccountConflictError

X_HANDLE_RE = re.compile(r"[a-z0-9_]{1,15}")


class XWatchStore(Protocol):
    def list_x_watch_accounts(self) -> list[dict[str, Any]]: ...

    def get_x_watch_account(self, account_id: int) -> Mapping[str, Any] | None: ...

    def create_x_watch_account(
        self,
        payload: dict[str, Any],
    ) -> Mapping[str, Any]: ...

    def update_x_watch_account(
        self,
        account_id: int,
        payload: dict[str, Any],
    ) -> Mapping[str, Any] | None: ...

    def delete_x_watch_account(self, account_id: int) -> bool: ...

    def update_x_watch_test_result(
        self,
        account_id: int,
        result: Mapping[str, Any],
    ) -> Mapping[str, Any] | None: ...


@dataclass(frozen=True, slots=True)
class SafeXWatchAccountProjection:
    id: int
    screen_name: str
    display_name: str
    note: str
    enabled: bool
    sort_order: int
    last_test_status: str
    last_test_message: str
    last_test_at: str | None
    created_at: str | None
    updated_at: str | None


def project_account(row: Mapping[str, Any]) -> SafeXWatchAccountProjection:
    return SafeXWatchAccountProjection(
        id=int(row.get("id") or 0),
        screen_name=str(row.get("screen_name") or ""),
        display_name=str(row.get("display_name") or ""),
        note=str(row.get("note") or ""),
        enabled=bool(row.get("enabled")),
        sort_order=int(row.get("sort_order") or 0),
        last_test_status=str(row.get("last_test_status") or "unknown"),
        last_test_message=str(row.get("last_test_message") or ""),
        last_test_at=_optional_string(row.get("last_test_at")),
        created_at=_optional_string(row.get("created_at")),
        updated_at=_optional_string(row.get("updated_at")),
    )


def _optional_string(value: Any) -> str | None:
    return str(value) if value is not None else None


@dataclass(frozen=True, slots=True)
class XWatchTestOutcome:
    result: dict[str, Any]
    account: Mapping[str, Any] | SafeXWatchAccountProjection


class XWatchAdminValidationError(ValueError):
    pass


class XWatchAdminNotFoundError(LookupError):
    pass


class XWatchAdminConflictError(RuntimeError):
    pass


XWatchTester = Callable[[str], Mapping[str, Any]]


class XWatchAdminService:
    """关注账号管理 + 手动测活。

    手动测活是轻量探测（单账号 1-2 次请求），刻意不持有 X 操作大锁：
    大锁只串行采集/回填等重路径（共享出口 IP，叠加会放大 429），
    手动测试与采集并发执行互不干扰。
    """

    def __init__(
        self,
        store: XWatchStore,
        tester: XWatchTester | None = None,
    ) -> None:
        self._store = store
        self._tester = tester

    async def list_accounts(self) -> list[SafeXWatchAccountProjection]:
        rows = await asyncio.to_thread(self._store.list_x_watch_accounts)
        return [project_account(row) for row in rows]

    async def create_account(
        self,
        values: Mapping[str, Any],
    ) -> SafeXWatchAccountProjection:
        payload = normalize_account_payload(values)
        try:
            row = await asyncio.to_thread(
                self._store.create_x_watch_account,
                payload,
            )
        except XWatchAccountConflictError as exc:
            raise XWatchAdminConflictError("该 X 账号已在关注列表中") from exc
        return project_account(row)

    async def update_account(
        self,
        account_id: int,
        values: Mapping[str, Any],
    ) -> SafeXWatchAccountProjection:
        payload = normalize_account_payload(values)
        try:
            row = await asyncio.to_thread(
                self._store.update_x_watch_account,
                account_id,
                payload,
            )
        except XWatchAccountConflictError as exc:
            raise XWatchAdminConflictError("该 X 账号已在关注列表中") from exc
        if row is None:
            raise XWatchAdminNotFoundError("X 关注账号不存在")
        return project_account(row)

    async def delete_account(self, account_id: int) -> None:
        deleted = await asyncio.to_thread(
            self._store.delete_x_watch_account,
            account_id,
        )
        if not deleted:
            raise XWatchAdminNotFoundError("X 关注账号不存在")

    async def test_account(self, account_id: int) -> XWatchTestOutcome:
        if self._tester is None:
            raise RuntimeError("X watch account tester is not configured")
        outcome = await asyncio.to_thread(
            self.test_connection,
            account_id,
            self._tester,
        )
        if outcome is None:
            raise XWatchAdminNotFoundError("X 关注账号不存在")
        return XWatchTestOutcome(
            result=outcome.result,
            account=project_account(outcome.account),
        )

    def test_connection(
        self,
        account_id: int,
        tester: XWatchTester,
    ) -> XWatchTestOutcome | None:
        row = self._store.get_x_watch_account(account_id)
        if row is None:
            return None
        result = tester(str(row.get("screen_name") or ""))
        updated = self._store.update_x_watch_test_result(account_id, result)
        return XWatchTestOutcome(result=dict(result), account=updated or row)


def normalize_account_payload(values: Mapping[str, Any]) -> dict[str, Any]:
    screen_name = normalize_x_screen_name(values.get("screen_name"))
    if not re.fullmatch(X_HANDLE_RE, screen_name):
        raise XWatchAdminValidationError(
            "X 账号 handle 仅支持 1-15 位字母、数字和下划线"
        )
    try:
        sort_order = int(values.get("sort_order", 0))
    except (TypeError, ValueError) as exc:
        raise XWatchAdminValidationError("sort_order 必须为整数") from exc
    return {
        "screen_name": screen_name,
        "display_name": str(values.get("display_name") or "").strip(),
        "note": str(values.get("note") or "").strip(),
        "enabled": bool(values.get("enabled", True)),
        "sort_order": sort_order,
    }
