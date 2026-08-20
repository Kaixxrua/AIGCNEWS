from __future__ import annotations

import asyncio
import time
from typing import Any, Mapping
from unittest.mock import MagicMock

import pytest

from backend.app.services.x_credentials.admin_service import (
    XCredentialAdminNotFoundError,
    XCredentialAdminService,
    XCredentialAdminValidationError,
    normalize_credential_payload,
    project_credential,
)


def _row(**overrides):
    row = {
        "id": 7,
        "display_name": "Primary X",
        "note": "main cookie pair",
        "auth_token": "auth-token-secret",
        "ct0": "ct0-token-secret",
        "enabled": True,
        "sort_order": 0,
        "last_test_status": "unknown",
        "last_test_message": "",
        "last_test_at": None,
        "created_at": None,
        "updated_at": None,
    }
    row.update(overrides)
    return row


def test_safe_projection_masks_write_only_secrets() -> None:
    projection = project_credential(_row())

    assert projection.auth_token_configured is True
    assert projection.auth_token_masked == "auth****cret"
    assert projection.ct0_configured is True
    assert projection.ct0_masked == "ct0-****cret"
    assert not hasattr(projection, "auth_token")
    assert not hasattr(projection, "ct0")
    assert "auth-token-secret" not in repr(projection)
    assert "ct0-token-secret" not in repr(projection)


def test_create_requires_complete_secret_pair_and_normalizes_fields() -> None:
    with pytest.raises(XCredentialAdminValidationError, match="显示名称"):
        normalize_credential_payload({}, creating=True)
    with pytest.raises(XCredentialAdminValidationError, match="同时提供"):
        normalize_credential_payload(
            {"display_name": "Primary", "auth_token": "auth"},
            creating=True,
        )

    payload = normalize_credential_payload(
        {
            "display_name": " Primary X ",
            "note": " production ",
            "enabled": False,
            "sort_order": "3",
            "auth_token": " auth-secret ",
            "ct0": " ct0-secret ",
        },
        creating=True,
    )

    assert payload == {
        "display_name": "Primary X",
        "note": "production",
        "enabled": False,
        "sort_order": 3,
        "auth_token": "auth-secret",
        "ct0": "ct0-secret",
    }


def test_update_retains_both_blank_secrets_and_rejects_half_pair() -> None:
    payload = normalize_credential_payload(
        {
            "display_name": "Primary X",
            "auth_token": "",
            "ct0": None,
        },
        creating=False,
    )
    assert payload["auth_token"] is None
    assert payload["ct0"] is None

    with pytest.raises(XCredentialAdminValidationError, match="仅提供 auth_token"):
        normalize_credential_payload(
            {"display_name": "Primary X", "auth_token": "new", "ct0": ""},
            creating=False,
        )
    with pytest.raises(XCredentialAdminValidationError, match="仅提供 ct0"):
        normalize_credential_payload(
            {"display_name": "Primary X", "auth_token": None, "ct0": "new"},
            creating=False,
        )


def test_crud_projects_rows_and_maps_missing_records() -> None:
    store = MagicMock()
    store.list_x_credentials.return_value = [_row()]
    store.create_x_credential.return_value = _row(id=8)
    store.update_x_credential.return_value = _row(display_name="Backup X")
    store.delete_x_credential.return_value = True
    service = XCredentialAdminService(store)
    values = {
        "display_name": " Primary X ",
        "note": " production ",
        "enabled": True,
        "sort_order": 0,
        "auth_token": " auth-secret ",
        "ct0": " ct0-secret ",
    }

    listed = asyncio.run(service.list_credentials())
    created = asyncio.run(service.create_credential(values))
    updated = asyncio.run(service.update_credential(7, values))
    asyncio.run(service.delete_credential(7))

    assert listed[0].id == 7
    assert created.id == 8
    assert updated.display_name == "Backup X"
    assert created.auth_token_masked == "auth****cret"
    store.create_x_credential.assert_called_once()
    store.update_x_credential.assert_called_once()
    store.delete_x_credential.assert_called_once_with(7)

    store.update_x_credential.return_value = None
    with pytest.raises(XCredentialAdminNotFoundError, match="不存在"):
        asyncio.run(service.update_credential(99, values))
    store.delete_x_credential.return_value = False
    with pytest.raises(XCredentialAdminNotFoundError, match="不存在"):
        asyncio.run(service.delete_credential(99))


def test_single_credential_probe_persists_safe_result_without_fallback() -> None:
    raw = _row()
    updated = _row(last_test_status="failed", last_test_message="x_auth_expired")
    store = MagicMock()
    store.get_x_credential.return_value = raw
    store.update_x_credential_test_result.return_value = updated
    tester = MagicMock(return_value={"status": "failed", "message": "x_auth_expired"})
    service = XCredentialAdminService(store, tester)

    outcome = asyncio.run(service.test_credential(7, "openai"))

    tester.assert_called_once_with(raw, "openai")
    store.update_x_credential_test_result.assert_called_once_with(
        7,
        {"status": "failed", "message": "x_auth_expired"},
    )
    assert outcome.result == {"status": "failed", "message": "x_auth_expired"}
    assert outcome.credential.auth_token_masked == "auth****cret"
    assert "auth-token-secret" not in repr(outcome)

    store.get_x_credential.return_value = None
    with pytest.raises(XCredentialAdminNotFoundError, match="不存在"):
        asyncio.run(service.test_credential(99, "openai"))
    assert tester.call_count == 1


def test_credential_tests_run_concurrently_without_shared_lock() -> None:
    """手动凭证测试走轻量并发道：不与其它 X 操作串行。

    X 操作大锁只保护采集/回填/凭证池测活等重路径（共享出口 IP，叠加放大
    429）；单次手动探测并发执行互不干扰——若退回持锁实现，两个测试会串行
    （enter/exit 交替），本用例的 enter/enter 交错断言立即变红。
    """
    timestamps: list[tuple[str, float]] = []
    call_count = {"n": 0}

    def slow_tester(credential: Mapping[str, Any], handle: str) -> Mapping[str, Any]:
        call_count["n"] += 1
        timestamps.append(("enter", time.monotonic()))
        time.sleep(0.05)
        timestamps.append(("exit", time.monotonic()))
        return {"status": "succeeded", "message": "ok"}

    row = _row()
    store = MagicMock()
    store.get_x_credential.return_value = row
    store.update_x_credential_test_result.return_value = row
    service = XCredentialAdminService(store, slow_tester)

    async def run_both() -> None:
        await asyncio.gather(
            service.test_credential(1, "openai"),
            service.test_credential(2, "karpathy"),
        )

    asyncio.run(run_both())

    assert len(timestamps) == 4
    sorted_timestamps = sorted(timestamps, key=lambda item: item[1])
    # 并发交错：两个 enter 都先于任一 exit（串行实现为 enter/exit/enter/exit）
    assert sorted_timestamps[0][0] == "enter"
    assert sorted_timestamps[1][0] == "enter"
    assert call_count["n"] == 2
