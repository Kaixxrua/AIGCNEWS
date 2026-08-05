from __future__ import annotations

from contextlib import contextmanager
from datetime import time
from unittest.mock import MagicMock

import pytest

from backend.app.repositories.postgres_scheduler_job_config_repository import (
    PostgresSchedulerJobConfigRepository,
)
from backend.app.repositories.scheduler_job_config_repository import (
    SchedulerJobConfig,
    SchedulerJobConfigRepository,
)


class FakeDatabase:
    def __init__(self, cursor: MagicMock) -> None:
        self.cursor = cursor
        self.connection = MagicMock()
        cursor_context = MagicMock()
        cursor_context.__enter__.return_value = cursor
        self.connection.cursor.return_value = cursor_context
        self.transaction_count = 0

    @contextmanager
    def transaction(self):
        self.transaction_count += 1
        yield self.connection


def _make_repository(cursor: MagicMock | None = None):
    cursor = cursor or MagicMock()
    database = FakeDatabase(cursor)
    return PostgresSchedulerJobConfigRepository(database), database, cursor


def test_adapter_exposes_scheduler_job_config_repository_contract() -> None:
    repository, _, _ = _make_repository()
    contract: SchedulerJobConfigRepository = repository

    assert callable(contract.list_scheduler_job_configs)
    assert callable(contract.get_scheduler_job_config)
    assert callable(contract.upsert_scheduler_job_config)


def test_list_orders_configs_by_job_id() -> None:
    repository, _, cursor = _make_repository()
    cursor.fetchall.return_value = [
        {
            "job_id": "github_trending",
            "start_time": time(0, 0),
            "end_time": time(23, 59),
            "interval_minutes": 60,
            "enabled": True,
        },
        {
            "job_id": "arxiv_papers",
            "start_time": time(8, 0),
            "end_time": time(20, 0),
            "interval_minutes": 120,
            "enabled": False,
        },
    ]

    result = repository.list_scheduler_job_configs()

    assert [config.job_id for config in result] == ["github_trending", "arxiv_papers"]
    assert result[1] == SchedulerJobConfig(
        job_id="arxiv_papers",
        start_time=time(8, 0),
        end_time=time(20, 0),
        interval_minutes=120,
        enabled=False,
    )


def test_get_returns_config_or_none() -> None:
    repository, _, cursor = _make_repository()
    cursor.fetchone.return_value = {
        "job_id": "daily_briefing",
        "start_time": time(8, 0),
        "end_time": time(8, 1),
        "interval_minutes": 1440,
        "enabled": True,
    }

    found = repository.get_scheduler_job_config("daily_briefing")
    assert found is not None
    assert found.interval_minutes == 1440

    cursor.fetchone.return_value = None
    missing = repository.get_scheduler_job_config("missing")
    assert missing is None


def test_upsert_validates_inputs() -> None:
    repository, _, _ = _make_repository()

    with pytest.raises(ValueError, match="job_id"):
        repository.upsert_scheduler_job_config(
            "   ",
            start_time=time(0, 0),
            end_time=time(1, 0),
            interval_minutes=30,
        )

    with pytest.raises(ValueError, match="interval_minutes"):
        repository.upsert_scheduler_job_config(
            "arxiv_papers",
            start_time=time(0, 0),
            end_time=time(1, 0),
            interval_minutes=0,
        )

    with pytest.raises(ValueError, match="start_time"):
        repository.upsert_scheduler_job_config(
            "arxiv_papers",
            start_time=time(12, 0),
            end_time=time(8, 0),
            interval_minutes=30,
        )


def test_upsert_persists_and_returns_config() -> None:
    repository, _, cursor = _make_repository()
    cursor.fetchone.return_value = {
        "job_id": "arxiv_papers",
        "start_time": time(9, 0),
        "end_time": time(17, 0),
        "interval_minutes": 90,
        "enabled": False,
    }

    result = repository.upsert_scheduler_job_config(
        "arxiv_papers",
        start_time=time(9, 0),
        end_time=time(17, 0),
        interval_minutes=90,
        enabled=False,
    )

    assert result == SchedulerJobConfig(
        job_id="arxiv_papers",
        start_time=time(9, 0),
        end_time=time(17, 0),
        interval_minutes=90,
        enabled=False,
    )
    query = cursor.execute.call_args_list[0].args[0]
    assert "INSERT INTO scheduler_job_config" in query
    assert "ON CONFLICT (job_id) DO UPDATE SET" in query
