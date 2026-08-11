from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastapi_cache import FastAPICache
from fastapi_cache.backends.inmemory import InMemoryBackend

from backend.app.api import routes_dashboard
from backend.app.api.dependencies import (
    get_github_hot_board_reader,
    get_rank_snapshot_repository,
)
from backend.app.services.dashboard import policy

# 分源定稿契约（PR1）：
# 每个源有自己的自然日界（SOURCE_DAY_BOUNDARY）与关榜时刻
# （SOURCE_FINALIZE_HOUR，次日 CST 整点）。CST 源次日 01:00 揭榜，
# PT 源（HF/PH）次日 17:00 揭榜。整榜 is_finalized/is_embargoed
# 一刀切语义不变；source_status 只增不破地透出分源状态。

EXPECTED_SOURCE_ORDER = ["arxiv", "github", "news", "producthunt", "hackernews", "x"]
PT_SOURCES = {"arxiv", "producthunt"}
CST_SOURCES = {"github", "news", "hackernews", "x"}


def _freeze_now(monkeypatch: Any, year: int, month: int, day: int, hour: int) -> None:
    class _FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz: Any = None) -> datetime:
            value = cls(year, month, day, hour, 0, 0)
            return value.replace(tzinfo=tz) if tz else value

    monkeypatch.setattr(policy, "datetime", _FrozenDateTime)


class _FakeRankSnapshotReader:
    def get_snapshot_documents(
        self,
        snapshot_date: str,
        source_channel: str | None = None,
        source_type: str | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        return []

    def get_snapshot_dates(
        self,
        limit: int = 60,
        source: str | None = None,
        period: str | None = None,
    ) -> list[str]:
        return []

    def get_snapshot_source_counts(self, snapshot_date: str) -> dict[str, int]:
        return {}

    def get_snapshot_doc_ids(
        self,
        snapshot_date: str,
        source_channel: str | None = None,
    ) -> set[str]:
        return set()


class _FakeGitHubHotReader:
    def list_github_hot_for_date(
        self,
        *,
        metric_date: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        return []

    def list_github_hot_dates(self, *, limit: int = 60) -> list[str]:
        return []


def _top_client() -> TestClient:
    app = FastAPI()
    app.include_router(routes_dashboard.router, prefix="/api")
    app.dependency_overrides[get_rank_snapshot_repository] = (
        lambda: _FakeRankSnapshotReader()
    )
    app.dependency_overrides[get_github_hot_board_reader] = (
        lambda: _FakeGitHubHotReader()
    )
    return TestClient(app)


def test_finalize_schedule_pins_sources_boundaries_and_hours() -> None:
    assert list(policy.SOURCE_FINALIZE_HOUR.keys()) == EXPECTED_SOURCE_ORDER
    assert set(policy.SOURCE_DAY_BOUNDARY.keys()) == set(EXPECTED_SOURCE_ORDER)
    for source in PT_SOURCES:
        assert policy.SOURCE_DAY_BOUNDARY[source] == "PT"
        # PT 源次日 17:00 揭榜：PST 冬令时 PT 0:00 = CST 16:00 + 1h 采集窗口
        assert policy.SOURCE_FINALIZE_HOUR[source] == 17
    for source in CST_SOURCES:
        assert policy.SOURCE_DAY_BOUNDARY[source] == "CST"
        # CST 源次日 01:00 揭榜：00:3x 关榜采集收完当天尾巴
        assert policy.SOURCE_FINALIZE_HOUR[source] == 1


def test_source_status_today_is_draft_for_all_sources(monkeypatch: Any) -> None:
    _freeze_now(monkeypatch, 2026, 8, 10, 10)
    status_map = policy.compute_source_status_map("2026-08-10")
    assert list(status_map.keys()) == EXPECTED_SOURCE_ORDER
    for status in status_map.values():
        assert status["is_finalized"] is False
        assert status["is_embargoed"] is False
        assert status["day_boundary"] in ("PT", "CST")


def test_source_status_yesterday_before_any_close_all_embargoed(
    monkeypatch: Any,
) -> None:
    _freeze_now(monkeypatch, 2026, 8, 11, 0)
    status_map = policy.compute_source_status_map("2026-08-10")
    for status in status_map.values():
        assert status["is_finalized"] is False
        assert status["is_embargoed"] is True


def test_source_status_yesterday_cst_sources_finalize_before_pt_sources(
    monkeypatch: Any,
) -> None:
    """分源发散的核心契约：同一时刻，CST 源已定稿而 PT 源仍在静默期。"""
    _freeze_now(monkeypatch, 2026, 8, 11, 10)
    status_map = policy.compute_source_status_map("2026-08-10")
    for source in CST_SOURCES:
        assert status_map[source]["is_finalized"] is True, source
        assert status_map[source]["is_embargoed"] is False, source
    for source in PT_SOURCES:
        assert status_map[source]["is_finalized"] is False, source
        assert status_map[source]["is_embargoed"] is True, source


def test_source_status_yesterday_after_pt_close_all_finalized(
    monkeypatch: Any,
) -> None:
    _freeze_now(monkeypatch, 2026, 8, 11, 18)
    status_map = policy.compute_source_status_map("2026-08-10")
    for status in status_map.values():
        assert status["is_finalized"] is True
        assert status["is_embargoed"] is False


def test_source_status_older_dates_always_finalized(monkeypatch: Any) -> None:
    _freeze_now(monkeypatch, 2026, 8, 11, 3)
    status_map = policy.compute_source_status_map("2026-08-01")
    for status in status_map.values():
        assert status["is_finalized"] is True
        assert status["is_embargoed"] is False


def test_source_status_unknown_source_falls_back_to_legacy_envelope(
    monkeypatch: Any,
) -> None:
    _freeze_now(monkeypatch, 2026, 8, 11, 10)
    status = policy.compute_source_board_status("2026-08-10", "weibo")
    # 未知源回退旧版整榜口径：FINALIZE_HOUR(15) 之前仍静默
    assert status["is_embargoed"] is True
    assert status["is_finalized"] is False
    assert status["finalize_hour"] == policy.FINALIZE_HOUR
    assert status["day_boundary"] == policy.DEFAULT_SOURCE_DAY_BOUNDARY

    _freeze_now(monkeypatch, 2026, 8, 11, 16)
    status = policy.compute_source_board_status("2026-08-10", "weibo")
    assert status["is_finalized"] is True
    assert status["is_embargoed"] is False


def test_aggregate_board_status_semantics_unchanged(monkeypatch: Any) -> None:
    """整榜一刀切口径回归 pin：昨日 15 点前静默、之后定稿，与旧版一致。"""
    _freeze_now(monkeypatch, 2026, 8, 11, 10)
    assert policy.compute_board_status("2026-08-10") == {
        "is_finalized": False,
        "is_embargoed": True,
    }
    _freeze_now(monkeypatch, 2026, 8, 11, 16)
    assert policy.compute_board_status("2026-08-10") == {
        "is_finalized": True,
        "is_embargoed": False,
    }
    assert policy.compute_board_status("2026-08-11") == {
        "is_finalized": False,
        "is_embargoed": False,
    }


def test_top_route_response_adds_source_status_and_keeps_legacy_fields(
    monkeypatch: Any,
) -> None:
    from backend.app.core.config import settings

    monkeypatch.setattr(settings, "x_source_enabled", True)
    _freeze_now(monkeypatch, 2026, 8, 11, 10)
    FastAPICache.init(InMemoryBackend(), prefix="dashboard-src-status-normal")
    try:
        response = _top_client().get("/api/dashboard/top?date=2026-08-01")
    finally:
        FastAPICache.reset()

    assert response.status_code == 200
    payload = response.json()
    # 既有字段原样保留（wire 只增不破）
    for key in (
        "items",
        "total",
        "period",
        "snapshot_date",
        "requested_date",
        "resolved_date",
        "stale",
        "is_finalized",
        "is_embargoed",
    ):
        assert key in payload, key
    assert payload["is_finalized"] is True
    assert payload["is_embargoed"] is False

    status_map = payload["source_status"]
    assert list(status_map.keys()) == EXPECTED_SOURCE_ORDER
    for status in status_map.values():
        assert set(status.keys()) == {
            "is_finalized",
            "is_embargoed",
            "day_boundary",
            "finalize_hour",
            "is_disabled",
        }
        assert status["is_finalized"] is True
        assert status["is_embargoed"] is False
        assert status["is_disabled"] is False
    assert status_map["github"]["finalize_hour"] == 1
    assert status_map["github"]["day_boundary"] == "CST"
    assert status_map["arxiv"]["finalize_hour"] == 17
    assert status_map["arxiv"]["day_boundary"] == "PT"
    assert status_map["producthunt"]["finalize_hour"] == 17


def test_top_route_embargoed_response_carries_divergent_source_status(
    monkeypatch: Any,
) -> None:
    """整榜静默期拦截不变，但 source_status 如实透出分源发散状态。"""
    from backend.app.core.config import settings

    monkeypatch.setattr(settings, "x_source_enabled", True)
    _freeze_now(monkeypatch, 2026, 8, 11, 10)
    FastAPICache.init(InMemoryBackend(), prefix="dashboard-src-status-embargo")
    try:
        response = _top_client().get("/api/dashboard/top?date=2026-08-10")
    finally:
        FastAPICache.reset()

    assert response.status_code == 200
    payload = response.json()
    assert payload["items"] == []
    assert payload["is_embargoed"] is True
    assert payload["is_finalized"] is False

    status_map = payload["source_status"]
    # CST 源已过 01:00 关榜点：分源视角已定稿；整榜闸门仍静默
    assert status_map["github"]["is_finalized"] is True
    assert status_map["x"]["is_finalized"] is True
    # PT 源未到 17:00：仍在静默期
    assert status_map["arxiv"]["is_embargoed"] is True
    assert status_map["producthunt"]["is_embargoed"] is True


def test_source_status_marks_disabled_pluggable_sources(monkeypatch: Any) -> None:
    """可插拔源开关关闭时 is_disabled=True（其余字段照常计算），开启全部 False。"""
    from backend.app.core.config import settings

    _freeze_now(monkeypatch, 2026, 8, 10, 10)
    monkeypatch.setattr(settings, "x_source_enabled", False)
    status_map = policy.compute_source_status_map("2026-08-10")
    assert list(status_map.keys()) == EXPECTED_SOURCE_ORDER
    assert status_map["x"]["is_disabled"] is True
    # 关态不改既有定稿/静默语义
    assert status_map["x"]["is_finalized"] is False
    assert status_map["x"]["is_embargoed"] is False
    for source in EXPECTED_SOURCE_ORDER:
        if source != "x":
            assert status_map[source]["is_disabled"] is False, source

    monkeypatch.setattr(settings, "x_source_enabled", True)
    status_map = policy.compute_source_status_map("2026-08-10")
    assert all(status["is_disabled"] is False for status in status_map.values())


def test_top_route_marks_disabled_source_in_wire(monkeypatch: Any) -> None:
    from backend.app.core.config import settings

    monkeypatch.setattr(settings, "x_source_enabled", False)
    _freeze_now(monkeypatch, 2026, 8, 11, 10)
    FastAPICache.init(InMemoryBackend(), prefix="dashboard-src-status-disabled")
    try:
        response = _top_client().get("/api/dashboard/top?date=2026-08-01")
    finally:
        FastAPICache.reset()

    assert response.status_code == 200
    status_map = response.json()["source_status"]
    assert status_map["x"]["is_disabled"] is True
    for source, status in status_map.items():
        if source != "x":
            assert status["is_disabled"] is False, source
