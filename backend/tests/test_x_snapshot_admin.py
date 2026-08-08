from __future__ import annotations

import unittest

from backend.app.services.x_snapshot_admin import XSnapshotAdminService


class FakeBackfillDocuments:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def list_x_snapshot_backfill_rows(self) -> list[dict]:
        return list(self._rows)


class FakeRankSnapshots:
    def __init__(self) -> None:
        self.upserts: list[dict] = []

    def upsert_rank_snapshot(
        self,
        doc_id: str,
        snapshot_date: str,
        source_channel: str,
        rank_in_period: int,
        raw_score: float,
        score: float,
    ) -> None:
        self.upserts.append(
            {
                "doc_id": doc_id,
                "snapshot_date": snapshot_date,
                "source_channel": source_channel,
                "rank_in_period": rank_in_period,
                "raw_score": raw_score,
                "score": score,
            }
        )


def _service(rows: list[dict]) -> tuple[XSnapshotAdminService, FakeRankSnapshots]:
    snapshots = FakeRankSnapshots()
    service = XSnapshotAdminService(
        documents=FakeBackfillDocuments(rows),
        rank_snapshots=snapshots,
    )
    return service, snapshots


class XSnapshotAdminRebuildTests(unittest.TestCase):
    def test_groups_by_cst_day_with_utc_rollover(self) -> None:
        # UTC 8/6 19:13 = CST 8/7 03:13 —— 归属 CST 发布日，与采集器同一约定
        rows = [
            {"id": "x:1", "published_at": "2026-08-06T19:13:48+00:00", "raw_score": 10.0, "score": 0.0},
            {"id": "x:2", "published_at": "2026-08-07T01:00:00+00:00", "raw_score": 20.0, "score": 1.0},
        ]
        service, snapshots = _service(rows)

        outcome = service.rebuild()

        self.assertEqual(
            outcome["results"],
            [{"date": "2026-08-07", "upserted": 2}],
        )
        self.assertEqual(outcome["skipped_no_date"], 0)
        self.assertEqual(
            [u["snapshot_date"] for u in snapshots.upserts],
            ["2026-08-07", "2026-08-07"],
        )
        self.assertTrue(
            all(u["source_channel"] == "x_daily_watchlist" for u in snapshots.upserts)
        )

    def test_ranks_by_engagement_score_descending(self) -> None:
        rows = [
            {"id": "x:low", "published_at": "2026-08-07T01:00:00+00:00", "raw_score": 5.0, "score": 0.0},
            {"id": "x:high", "published_at": "2026-08-07T02:00:00+00:00", "raw_score": 99.0, "score": 0.0},
            {"id": "x:mid", "published_at": "2026-08-07T03:00:00+00:00", "raw_score": 50.0, "score": 0.0},
        ]
        service, snapshots = _service(rows)

        service.rebuild()

        self.assertEqual(
            [(u["doc_id"], u["rank_in_period"]) for u in snapshots.upserts],
            [("x:high", 1), ("x:mid", 2), ("x:low", 3)],
        )

    def test_raw_score_zero_falls_back_to_score(self) -> None:
        rows = [
            {"id": "x:1", "published_at": "2026-08-07T01:00:00+00:00", "raw_score": 0.0, "score": 7.5},
        ]
        service, snapshots = _service(rows)

        service.rebuild()

        self.assertEqual(snapshots.upserts[0]["raw_score"], 7.5)
        self.assertEqual(snapshots.upserts[0]["score"], 7.5)

    def test_target_date_filters_other_days(self) -> None:
        rows = [
            {"id": "x:old", "published_at": "2026-07-30T01:00:00+00:00", "raw_score": 3.0, "score": 0.0},
            {"id": "x:new", "published_at": "2026-08-07T01:00:00+00:00", "raw_score": 9.0, "score": 0.0},
        ]
        service, snapshots = _service(rows)

        outcome = service.rebuild("2026-07-30")

        self.assertEqual(outcome["results"], [{"date": "2026-07-30", "upserted": 1}])
        self.assertEqual([u["doc_id"] for u in snapshots.upserts], ["x:old"])

    def test_unparseable_or_missing_dates_are_skipped_and_counted(self) -> None:
        rows = [
            {"id": "x:empty", "published_at": "", "raw_score": 1.0, "score": 0.0},
            {"id": "x:none", "published_at": None, "raw_score": 1.0, "score": 0.0},
            {"id": "x:bad", "published_at": "not-a-date", "raw_score": 1.0, "score": 0.0},
            {"id": "x:ok", "published_at": "2026-08-07T01:00:00+00:00", "raw_score": 1.0, "score": 0.0},
        ]
        service, snapshots = _service(rows)

        outcome = service.rebuild()

        self.assertEqual(outcome["skipped_no_date"], 3)
        self.assertEqual(len(snapshots.upserts), 1)

    def test_z_suffix_and_naive_timestamps_are_accepted(self) -> None:
        rows = [
            {"id": "x:z", "published_at": "2026-08-07T01:00:00Z", "raw_score": 1.0, "score": 0.0},
            {"id": "x:naive", "published_at": "2026-08-07T01:00:00", "raw_score": 2.0, "score": 0.0},
        ]
        service, snapshots = _service(rows)

        outcome = service.rebuild()

        # Z = UTC、naive 按 UTC 处理，两者都归 CST 8/7
        self.assertEqual(outcome["results"], [{"date": "2026-08-07", "upserted": 2}])

    def test_rows_without_id_never_reach_writer(self) -> None:
        rows = [
            {"id": "", "published_at": "2026-08-07T01:00:00+00:00", "raw_score": 1.0, "score": 0.0},
        ]
        service, snapshots = _service(rows)

        outcome = service.rebuild()

        self.assertEqual(outcome["results"], [])
        self.assertEqual(snapshots.upserts, [])

    def test_empty_input_returns_empty_results(self) -> None:
        service, snapshots = _service([])

        outcome = service.rebuild()

        self.assertEqual(outcome, {"results": [], "skipped_no_date": 0})
        self.assertEqual(snapshots.upserts, [])


if __name__ == "__main__":
    unittest.main()
