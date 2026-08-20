from __future__ import annotations

import asyncio
import time
import unittest
from typing import Any, Mapping
from unittest.mock import MagicMock

from backend.app.repositories.x_watch_repository import XWatchAccountConflictError
from backend.app.services.x_watch.admin_service import (
    XWatchAdminConflictError,
    XWatchAdminNotFoundError,
    XWatchAdminService,
    XWatchAdminValidationError,
    project_account,
)


class XWatchAdminServiceTests(unittest.TestCase):
    def test_safe_projection_projects_scalar_fields(self) -> None:
        projection = project_account(
            {
                "id": 1,
                "screen_name": "openai",
                "display_name": "OpenAI",
                "note": "官方账号",
                "enabled": True,
                "sort_order": 3,
                "last_test_status": "succeeded",
                "last_test_message": "拉取 2 条",
                "last_test_at": None,
                "created_at": None,
                "updated_at": None,
            }
        )

        self.assertEqual(projection.screen_name, "openai")
        self.assertEqual(projection.sort_order, 3)
        self.assertIsNone(projection.last_test_at)

    def test_crud_commands_normalize_project_and_map_domain_outcomes(self) -> None:
        row = {
            "id": 42,
            "screen_name": "openai",
            "display_name": "OpenAI",
            "note": "",
            "enabled": True,
            "sort_order": 0,
        }
        store = MagicMock()
        store.list_x_watch_accounts.return_value = [row]
        store.create_x_watch_account.return_value = row
        store.update_x_watch_account.return_value = row
        store.delete_x_watch_account.return_value = True
        service = XWatchAdminService(store)
        values = {
            "screen_name": " @OpenAI ",
            "display_name": " OpenAI ",
            "note": " 官方 ",
            "enabled": True,
            "sort_order": "2",
        }

        listed = asyncio.run(service.list_accounts())
        created = asyncio.run(service.create_account(values))
        updated = asyncio.run(service.update_account(42, values))
        asyncio.run(service.delete_account(42))

        self.assertEqual(listed[0].id, 42)
        self.assertEqual(created.screen_name, "openai")
        self.assertEqual(updated.id, 42)
        expected_payload = {
            "screen_name": "openai",
            "display_name": "OpenAI",
            "note": "官方",
            "enabled": True,
            "sort_order": 2,
        }
        store.create_x_watch_account.assert_called_once_with(expected_payload)
        store.update_x_watch_account.assert_called_once_with(42, expected_payload)
        store.delete_x_watch_account.assert_called_once_with(42)

        store.create_x_watch_account.side_effect = XWatchAccountConflictError()
        with self.assertRaisesRegex(XWatchAdminConflictError, "已在关注列表中"):
            asyncio.run(service.create_account(values))

        store.update_x_watch_account.side_effect = None
        store.update_x_watch_account.return_value = None
        with self.assertRaisesRegex(XWatchAdminNotFoundError, "不存在"):
            asyncio.run(service.update_account(42, values))

        store.delete_x_watch_account.return_value = False
        with self.assertRaisesRegex(XWatchAdminNotFoundError, "不存在"):
            asyncio.run(service.delete_account(42))

    def test_invalid_payload_is_rejected_before_repository_calls(self) -> None:
        store = MagicMock()
        service = XWatchAdminService(store)

        with self.assertRaisesRegex(XWatchAdminValidationError, "handle"):
            asyncio.run(service.create_account({"screen_name": "not a handle!"}))
        with self.assertRaisesRegex(XWatchAdminValidationError, "sort_order"):
            asyncio.run(service.create_account({"screen_name": "openai", "sort_order": "abc"}))
        with self.assertRaisesRegex(XWatchAdminValidationError, "handle"):
            asyncio.run(service.create_account({"screen_name": "a" * 16}))

        store.create_x_watch_account.assert_not_called()

    def test_connection_test_reads_internal_row_then_persists_result(self) -> None:
        row = {"id": 42, "screen_name": "openai"}
        updated = {"id": 42, "screen_name": "openai", "last_test_status": "succeeded"}
        store = MagicMock()
        store.get_x_watch_account.return_value = row
        store.update_x_watch_test_result.return_value = updated
        tester = MagicMock(
            return_value={"status": "succeeded", "message": "成功拉取 2 条近期推文"}
        )

        outcome = XWatchAdminService(store).test_connection(42, tester)

        self.assertIsNotNone(outcome)
        tester.assert_called_once_with("openai")
        store.update_x_watch_test_result.assert_called_once_with(
            42,
            {"status": "succeeded", "message": "成功拉取 2 条近期推文"},
        )
        self.assertEqual(outcome.account, updated)

    def test_missing_connection_target_returns_none_without_testing(self) -> None:
        store = MagicMock()
        store.get_x_watch_account.return_value = None
        tester = MagicMock()

        outcome = XWatchAdminService(store).test_connection(42, tester)

        self.assertIsNone(outcome)
        tester.assert_not_called()
        store.update_x_watch_test_result.assert_not_called()

    def test_account_tests_run_concurrently_without_shared_lock(self) -> None:
        """手动关注账号测试走轻量并发道：不与其它 X 操作串行。

        X 操作大锁只保护采集/回填等重路径（共享出口 IP，叠加放大 429）；
        单次手动探测并发执行互不干扰——若退回持锁实现，enter/exit 会严格
        交替，本用例的 enter/enter 交错断言立即变红。
        """
        timestamps: list[tuple[str, float]] = []
        call_count = {"n": 0}

        def slow_tester(handle: str) -> Mapping[str, Any]:
            call_count["n"] += 1
            timestamps.append(("enter", time.monotonic()))
            time.sleep(0.05)
            timestamps.append(("exit", time.monotonic()))
            return {"status": "succeeded", "message": "ok"}

        row = {"id": 1, "screen_name": "openai"}
        store = MagicMock()
        store.get_x_watch_account.return_value = row
        store.update_x_watch_test_result.return_value = row
        service = XWatchAdminService(store, slow_tester)

        async def run_both() -> None:
            await asyncio.gather(
                service.test_account(1),
                service.test_account(2),
            )

        asyncio.run(run_both())

        self.assertEqual(len(timestamps), 4)
        sorted_timestamps = sorted(timestamps, key=lambda item: item[1])
        # 并发交错：两个 enter 都先于任一 exit（串行实现为 enter/exit/enter/exit）
        self.assertEqual(sorted_timestamps[0][0], "enter")
        self.assertEqual(sorted_timestamps[1][0], "enter")
        self.assertEqual(call_count["n"], 2)


if __name__ == "__main__":
    unittest.main()
