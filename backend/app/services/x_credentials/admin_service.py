from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Protocol

from backend.app.services.secret_masking import mask_token


class XCredentialStore(Protocol):
    def list_x_credentials(self) -> list[dict[str, Any]]: ...

    def get_x_credential(self, credential_id: int) -> Mapping[str, Any] | None: ...

    def create_x_credential(
        self,
        payload: dict[str, Any],
    ) -> Mapping[str, Any]: ...

    def update_x_credential(
        self,
        credential_id: int,
        payload: dict[str, Any],
    ) -> Mapping[str, Any] | None: ...

    def delete_x_credential(self, credential_id: int) -> bool: ...

    def update_x_credential_test_result(
        self,
        credential_id: int,
        result: Mapping[str, Any],
    ) -> Mapping[str, Any] | None: ...


@dataclass(frozen=True, slots=True)
class SafeXCredentialProjection:
    id: int
    display_name: str
    note: str
    enabled: bool
    sort_order: int
    auth_token_configured: bool
    auth_token_masked: str | None
    ct0_configured: bool
    ct0_masked: str | None
    last_test_status: str
    last_test_message: str
    last_test_at: str | None
    created_at: str | None
    updated_at: str | None


def project_credential(row: Mapping[str, Any]) -> SafeXCredentialProjection:
    auth_token = str(row.get("auth_token") or "")
    ct0 = str(row.get("ct0") or "")
    return SafeXCredentialProjection(
        id=int(row.get("id") or 0),
        display_name=str(row.get("display_name") or ""),
        note=str(row.get("note") or ""),
        enabled=bool(row.get("enabled")),
        sort_order=int(row.get("sort_order") or 0),
        auth_token_configured=bool(auth_token),
        auth_token_masked=mask_token(auth_token),
        ct0_configured=bool(ct0),
        ct0_masked=mask_token(ct0),
        last_test_status=str(row.get("last_test_status") or "unknown"),
        last_test_message=str(row.get("last_test_message") or ""),
        last_test_at=_optional_string(row.get("last_test_at")),
        created_at=_optional_string(row.get("created_at")),
        updated_at=_optional_string(row.get("updated_at")),
    )


def _optional_string(value: Any) -> str | None:
    return str(value) if value is not None else None


@dataclass(frozen=True, slots=True)
class XCredentialTestOutcome:
    result: dict[str, Any]
    credential: Mapping[str, Any] | SafeXCredentialProjection


class XCredentialAdminValidationError(ValueError):
    pass


class XCredentialAdminNotFoundError(LookupError):
    pass


XCredentialTester = Callable[[Mapping[str, Any], str], Mapping[str, Any]]


class XCredentialAdminService:
    """凭证管理 + 手动测活。

    手动测活是轻量探测（单凭证 1-2 次请求），刻意不持有 X 操作大锁：
    大锁只串行采集/回填/凭证池测活等重路径（共享出口 IP，叠加会放大 429），
    手动测试与采集并发执行互不干扰。
    """

    def __init__(
        self,
        store: XCredentialStore,
        tester: XCredentialTester | None = None,
    ) -> None:
        self._store = store
        self._tester = tester

    async def list_credentials(self) -> list[SafeXCredentialProjection]:
        rows = await asyncio.to_thread(self._store.list_x_credentials)
        return [project_credential(row) for row in rows]

    async def create_credential(
        self,
        values: Mapping[str, Any],
    ) -> SafeXCredentialProjection:
        payload = normalize_credential_payload(values, creating=True)
        row = await asyncio.to_thread(self._store.create_x_credential, payload)
        return project_credential(row)

    async def update_credential(
        self,
        credential_id: int,
        values: Mapping[str, Any],
    ) -> SafeXCredentialProjection:
        payload = normalize_credential_payload(values, creating=False)
        row = await asyncio.to_thread(
            self._store.update_x_credential,
            credential_id,
            payload,
        )
        if row is None:
            raise XCredentialAdminNotFoundError("X 凭证不存在")
        return project_credential(row)

    async def delete_credential(self, credential_id: int) -> None:
        deleted = await asyncio.to_thread(
            self._store.delete_x_credential,
            credential_id,
        )
        if not deleted:
            raise XCredentialAdminNotFoundError("X 凭证不存在")

    async def test_credential(
        self,
        credential_id: int,
        probe_handle: str,
    ) -> XCredentialTestOutcome:
        if self._tester is None:
            raise RuntimeError("X credential tester is not configured")
        outcome = await asyncio.to_thread(
            self._test_connection,
            credential_id,
            probe_handle,
            self._tester,
        )
        if outcome is None:
            raise XCredentialAdminNotFoundError("X 凭证不存在")
        return XCredentialTestOutcome(
            result=outcome.result,
            credential=project_credential(outcome.credential),
        )

    def _test_connection(
        self,
        credential_id: int,
        probe_handle: str,
        tester: XCredentialTester,
    ) -> XCredentialTestOutcome | None:
        row = self._store.get_x_credential(credential_id)
        if row is None:
            return None
        result = tester(dict(row), probe_handle)
        updated = self._store.update_x_credential_test_result(
            credential_id,
            result,
        )
        return XCredentialTestOutcome(result=dict(result), credential=updated or row)


def normalize_credential_payload(
    values: Mapping[str, Any],
    *,
    creating: bool,
) -> dict[str, Any]:
    display_name = str(values.get("display_name") or "").strip()
    if not display_name:
        raise XCredentialAdminValidationError("请填写凭证显示名称")

    auth_token = _clean_secret(values.get("auth_token"))
    ct0 = _clean_secret(values.get("ct0"))

    if creating:
        if not auth_token or not ct0:
            raise XCredentialAdminValidationError(
                "创建 X 凭证必须同时提供 auth_token 和 ct0"
            )
    else:
        # Editing: empty/null secrets mean "retain current value".
        # The repository will fall back to the existing row when these are empty.
        if auth_token and not ct0:
            raise XCredentialAdminValidationError(
                "更新 X 凭证时不能仅提供 auth_token，必须同时提供 ct0 或都留空"
            )
        if ct0 and not auth_token:
            raise XCredentialAdminValidationError(
                "更新 X 凭证时不能仅提供 ct0，必须同时提供 auth_token 或都留空"
            )

    try:
        sort_order = int(values.get("sort_order", 0))
    except (TypeError, ValueError) as exc:
        raise XCredentialAdminValidationError("sort_order 必须为整数") from exc

    return {
        "display_name": display_name,
        "note": str(values.get("note") or "").strip(),
        "enabled": bool(values.get("enabled", True)),
        "sort_order": sort_order,
        "auth_token": auth_token or None,
        "ct0": ct0 or None,
    }


def _clean_secret(value: Any) -> str:
    return str(value or "").strip()
