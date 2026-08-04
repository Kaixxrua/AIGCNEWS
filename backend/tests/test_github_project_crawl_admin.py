from __future__ import annotations

import re
import threading
import unittest
from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from backend.app.services.github_project_crawl_admin import (
    CRAWL_TASK_PREFIX,
    RUN_ENRICH_BATCH,
    RUN_ENRICH_CONCURRENCY,
    RUN_ENRICH_MAX,
    GitHubProjectCrawlAdminService,
    plan_crawl,
)

NOW = datetime(2026, 8, 4, 12, 30, 15, 123456, tzinfo=timezone.utc)


def _plan(**overrides) -> dict:
    plan = plan_crawl(
        min_stars=500,
        max_stars=0,
        limit=100,
        created_start=date(2026, 1, 1),
        created_end=date(2026, 8, 4),
        now=NOW,
    )
    plan.update(overrides)
    return plan


class PlanCrawlTests(unittest.TestCase):
    def test_plan_generates_unique_channel_and_second_floored_anchor(self) -> None:
        plan = _plan()

        assert re.fullmatch(
            r"admin_crawl_20260804_123015_s500_[0-9a-f]{6}", plan["channel"]
        )
        assert plan["first_seen_after"] == "2026-08-04T12:30:15+00:00"
        assert plan["task_name"] == f"{CRAWL_TASK_PREFIX}{plan['channel']}"
        assert plan["enrich"] is True
        assert plan["min_stars"] == 500
        assert plan["max_stars"] == 0

    def test_plan_channels_do_not_collide_within_same_second(self) -> None:
        assert _plan()["channel"] != _plan()["channel"]

    def test_plan_rejects_invalid_windows(self) -> None:
        with pytest.raises(ValueError, match="max_stars"):
            plan_crawl(
                min_stars=500,
                max_stars=400,
                limit=10,
                created_start=date(2026, 1, 1),
                created_end=date(2026, 8, 4),
            )
        with pytest.raises(ValueError, match="created_end"):
            plan_crawl(
                min_stars=500,
                max_stars=0,
                limit=10,
                created_start=date(2026, 8, 4),
                created_end=date(2026, 1, 1),
            )
        with pytest.raises(ValueError, match="pushed_after"):
            plan_crawl(
                min_stars=500,
                max_stars=0,
                limit=10,
                created_start=date(2026, 1, 1),
                created_end=date(2026, 8, 4),
                pushed_after="2025-13-40",
            )


class CrawlAdminServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        # 类级锁跨用例隔离，避免相互污染
        self._original_lock = GitHubProjectCrawlAdminService._crawl_lock
        GitHubProjectCrawlAdminService._crawl_lock = threading.Lock()
        self.repositories = MagicMock()
        self.service = GitHubProjectCrawlAdminService(self.repositories)

    def tearDown(self) -> None:
        GitHubProjectCrawlAdminService._crawl_lock = self._original_lock

    def test_lock_is_mutually_exclusive_and_reentrant_after_release(self) -> None:
        assert self.service.try_acquire_crawl() is True
        assert self.service.try_acquire_crawl() is False
        self.service.release_crawl()
        assert self.service.try_acquire_crawl() is True
        self.service.release_crawl()

    def test_crawl_and_enrich_skips_enrichment_when_disabled(self) -> None:
        plan = _plan(enrich=False)
        self.repositories.ingestion_tasks.create_task.return_value = 7
        with patch(
            "backend.app.services.ingestion.github_search_crawl.crawl_github_search",
            return_value={"status": "success", "upserted": 12, "new_candidates": 9},
        ) as crawl:
            assert self.service.try_acquire_crawl() is True
            result = self.service.crawl_and_enrich(plan)

        assert result["status"] == "success"
        crawl.assert_called_once()
        crawl_kwargs = crawl.call_args.kwargs
        assert crawl_kwargs["channel"] == plan["channel"]
        assert crawl_kwargs["dry_run"] is False
        assert crawl_kwargs["ingestion"] is self.repositories.github_ingestion

        self.repositories.ingestion_tasks.create_task.assert_called_once_with(
            plan["task_name"]
        )
        self.repositories.ingestion_tasks.finish_task.assert_called_once_with(
            7, status="success", error_msg=None, item_count=12
        )
        # enrich=False：不触碰富化仓储
        self.repositories.github_enrichment.count_github_run_enrichment_candidates.assert_not_called()
        # 锁已释放，可再次获取
        assert self.service.try_acquire_crawl() is True
        self.service.release_crawl()

    def test_crawl_and_enrich_skips_enrichment_when_no_new_candidates(self) -> None:
        plan = _plan(enrich=True)
        self.repositories.ingestion_tasks.create_task.return_value = 7
        with patch(
            "backend.app.services.ingestion.github_search_crawl.crawl_github_search",
            return_value={"status": "success", "upserted": 4, "new_candidates": 0},
        ):
            self.service.try_acquire_crawl()
            result = self.service.crawl_and_enrich(plan)

        assert result["status"] == "success"
        assert result["enrichment"] is None
        self.repositories.github_enrichment.count_github_run_enrichment_candidates.assert_not_called()

    def test_crawl_and_enrich_enriches_run_scope_with_keyset_paging(self) -> None:
        plan = _plan(enrich=True)
        self.repositories.ingestion_tasks.create_task.return_value = 7
        enrichment = self.repositories.github_enrichment
        enrichment.count_github_run_enrichment_candidates.return_value = 3
        enrichment.list_github_run_enrichment_candidates.side_effect = [
            [{"repo_id": "a/r1"}, {"repo_id": "a/r2"}],
            [{"repo_id": "a/r3"}],
        ]
        enricher = MagicMock()
        enricher.enrich_rows.side_effect = [
            {"processed": 2, "succeeded": 2, "failed": 0},
            {"processed": 1, "succeeded": 0, "failed": 1},
        ]

        with (
            patch(
                "backend.app.services.ingestion.github_search_crawl.crawl_github_search",
                return_value={"status": "success", "upserted": 3, "new_candidates": 3},
            ),
            patch(
                "backend.app.services.ingestion.github_project_enricher.GitHubProjectEnricher",
                return_value=enricher,
            ) as enricher_cls,
        ):
            self.service.try_acquire_crawl()
            result = self.service.crawl_and_enrich(plan)

        assert result["status"] == "success"
        enrichment_result = result["enrichment"]
        assert enrichment_result == {
            "pending": 3,
            "target": 3,
            "processed": 3,
            "succeeded": 2,
            "failed": 1,
            "capped": False,
        }
        enricher_cls.assert_called_once_with(db=enrichment)
        # keyset 分页：第二批从上一批末尾 repo_id 继续
        list_calls = enrichment.list_github_run_enrichment_candidates.call_args_list
        assert list_calls[0].kwargs["after_repo_id"] == ""
        assert list_calls[0].kwargs["limit"] == min(RUN_ENRICH_BATCH, 3)
        assert list_calls[1].kwargs["after_repo_id"] == "a/r2"
        assert list_calls[1].kwargs["limit"] == 1
        for call in enricher.enrich_rows.call_args_list:
            assert call.kwargs["concurrency"] == RUN_ENRICH_CONCURRENCY
        self.repositories.ingestion_tasks.finish_task.assert_called_once_with(
            7, status="success", error_msg=None, item_count=3
        )

    def test_enrichment_is_capped_at_run_max(self) -> None:
        plan = _plan(enrich=True)
        self.repositories.ingestion_tasks.create_task.return_value = 7
        enrichment = self.repositories.github_enrichment
        enrichment.count_github_run_enrichment_candidates.return_value = RUN_ENRICH_MAX + 100
        enrichment.list_github_run_enrichment_candidates.side_effect = [
            [{"repo_id": f"a/r{i}"} for i in range(RUN_ENRICH_BATCH)],
            [{"repo_id": f"a/x{i}"} for i in range(RUN_ENRICH_BATCH)],
            [{"repo_id": f"a/y{i}"} for i in range(RUN_ENRICH_MAX - 2 * RUN_ENRICH_BATCH)],
        ]
        enricher = MagicMock()
        enricher.enrich_rows.side_effect = lambda rows, *, concurrency: {
            "processed": len(rows),
            "succeeded": len(rows),
            "failed": 0,
        }

        with (
            patch(
                "backend.app.services.ingestion.github_search_crawl.crawl_github_search",
                return_value={
                    "status": "success",
                    "upserted": RUN_ENRICH_MAX + 100,
                    "new_candidates": RUN_ENRICH_MAX + 100,
                },
            ),
            patch(
                "backend.app.services.ingestion.github_project_enricher.GitHubProjectEnricher",
                return_value=enricher,
            ),
        ):
            self.service.try_acquire_crawl()
            result = self.service.crawl_and_enrich(plan)

        assert result["enrichment"]["target"] == RUN_ENRICH_MAX
        assert result["enrichment"]["processed"] == RUN_ENRICH_MAX
        assert result["enrichment"]["capped"] is True

    def test_crawl_failure_marks_task_failed_and_releases_lock(self) -> None:
        plan = _plan()
        self.repositories.ingestion_tasks.create_task.return_value = 7
        with patch(
            "backend.app.services.ingestion.github_search_crawl.crawl_github_search",
            side_effect=RuntimeError("boom"),
        ):
            self.service.try_acquire_crawl()
            result = self.service.crawl_and_enrich(plan)

        assert result == {"status": "failed", "error": "boom"}
        self.repositories.ingestion_tasks.finish_task.assert_called_once_with(
            7, status="failed", error_msg="boom", item_count=0
        )
        assert self.service.try_acquire_crawl() is True
        self.service.release_crawl()

    def test_crawl_status_with_explicit_channel_and_anchor(self) -> None:
        self.repositories.ingestion_tasks.get_latest_task_by_name.return_value = {
            "id": 7,
            "task_name": f"{CRAWL_TASK_PREFIX}chan_x",
            "status": "running",
            "item_count": 0,
            "error_msg": None,
            "started_at": "2026-08-04T12:30:15+00:00",
            "finished_at": None,
        }
        self.repositories.github_enrichment.get_github_run_crawl_status.return_value = {
            "candidates_upserted": 10,
            "scope_total": 8,
            "enriched_succeeded": 5,
            "enriched_failed": 1,
        }

        status = self.service.crawl_status(
            channel="chan_x", first_seen_after="2026-08-04T12:00:00+00:00"
        )

        assert status["status"] == "running"
        assert status["channel"] == "chan_x"
        assert status["first_seen_after"] == "2026-08-04T12:00:00+00:00"
        assert status["task_id"] == 7
        assert status["candidates_upserted"] == 10
        assert status["scope_total"] == 8
        assert status["enriched_succeeded"] == 5
        assert status["enriched_failed"] == 1
        self.repositories.ingestion_tasks.get_latest_task_by_name.assert_called_once_with(
            f"{CRAWL_TASK_PREFIX}chan_x"
        )
        self.repositories.github_enrichment.get_github_run_crawl_status.assert_called_once_with(
            channel="chan_x",
            first_seen_after="2026-08-04T12:00:00+00:00",
            min_stars=500,
        )

    def test_crawl_status_defaults_to_latest_run_and_parses_channel(self) -> None:
        self.repositories.ingestion_tasks.get_latest_task_by_prefix.return_value = {
            "id": 9,
            "task_name": f"{CRAWL_TASK_PREFIX}admin_crawl_x",
            "status": "success",
            "item_count": 42,
            "error_msg": None,
            "started_at": "2026-08-04T12:30:15+00:00",
            "finished_at": "2026-08-04T12:45:00+00:00",
        }
        self.repositories.github_enrichment.get_github_run_crawl_status.return_value = {
            "candidates_upserted": 42,
            "scope_total": 42,
            "enriched_succeeded": 40,
            "enriched_failed": 2,
        }

        status = self.service.crawl_status()

        assert status["status"] == "success"
        assert status["channel"] == "admin_crawl_x"
        # 无显式锚点时回落到任务 started_at
        assert status["first_seen_after"] == "2026-08-04T12:30:15+00:00"
        assert status["item_count"] == 42
        assert status["finished_at"] == "2026-08-04T12:45:00+00:00"
        self.repositories.ingestion_tasks.get_latest_task_by_prefix.assert_called_once_with(
            CRAWL_TASK_PREFIX
        )
        self.repositories.ingestion_tasks.get_latest_task_by_name.assert_not_called()

    def test_crawl_status_idle_when_never_ran(self) -> None:
        self.repositories.ingestion_tasks.get_latest_task_by_prefix.return_value = None

        status = self.service.crawl_status()

        assert status["status"] == "idle"
        assert status["channel"] == ""
        assert status["task_id"] is None
        assert status["candidates_upserted"] == 0
        self.repositories.github_enrichment.get_github_run_crawl_status.assert_not_called()

    def test_crawl_status_rejects_invalid_anchor(self) -> None:
        with pytest.raises(ValueError, match="ISO 8601"):
            self.service.crawl_status(first_seen_after="not-a-date")

    def test_crawl_status_derives_min_stars_from_channel_marker(self) -> None:
        channel = "admin_crawl_20260804_123015_s50_ab12cd"
        self.repositories.ingestion_tasks.get_latest_task_by_name.return_value = {
            "id": 11,
            "task_name": f"{CRAWL_TASK_PREFIX}{channel}",
            "status": "running",
            "item_count": 0,
            "error_msg": None,
            "started_at": "2026-08-04T12:30:15+00:00",
            "finished_at": None,
        }
        self.repositories.github_enrichment.get_github_run_crawl_status.return_value = {}

        self.service.crawl_status(
            channel=channel, first_seen_after="2026-08-04T12:00:00+00:00"
        )

        self.repositories.github_enrichment.get_github_run_crawl_status.assert_called_once_with(
            channel=channel,
            first_seen_after="2026-08-04T12:00:00+00:00",
            min_stars=50,
        )

    def test_crawl_status_explicit_min_stars_overrides_channel_marker(self) -> None:
        channel = "admin_crawl_20260804_123015_s50_ab12cd"
        self.repositories.ingestion_tasks.get_latest_task_by_name.return_value = {
            "id": 12,
            "task_name": f"{CRAWL_TASK_PREFIX}{channel}",
            "status": "running",
            "item_count": 0,
            "error_msg": None,
            "started_at": "2026-08-04T12:30:15+00:00",
            "finished_at": None,
        }
        self.repositories.github_enrichment.get_github_run_crawl_status.return_value = {}

        self.service.crawl_status(
            channel=channel,
            first_seen_after="2026-08-04T12:00:00+00:00",
            min_stars=700,
        )

        self.repositories.github_enrichment.get_github_run_crawl_status.assert_called_once_with(
            channel=channel,
            first_seen_after="2026-08-04T12:00:00+00:00",
            min_stars=700,
        )


if __name__ == "__main__":
    unittest.main()
