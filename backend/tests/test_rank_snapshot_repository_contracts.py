from __future__ import annotations

import inspect
import unittest
from typing import Any

from backend.app.repositories.rank_snapshot_repository import (
    SNAPSHOT_PERIOD_CHANNELS,
    RankSnapshotAdminWriter,
    RankSnapshotReader,
    RankSnapshotRepository,
    RankSnapshotWriter,
)


def _without_annotations(function: Any) -> inspect.Signature:
    signature = inspect.signature(function)
    return signature.replace(
        parameters=[
            parameter.replace(annotation=inspect.Parameter.empty)
            for parameter in signature.parameters.values()
        ],
        return_annotation=inspect.Signature.empty,
    )


class RankSnapshotRepositoryContractTests(unittest.TestCase):
    def test_combined_repository_preserves_narrow_capabilities(self) -> None:
        for capability in (
            RankSnapshotReader,
            RankSnapshotWriter,
            RankSnapshotAdminWriter,
        ):
            self.assertIn(capability, RankSnapshotRepository.__mro__)

    def test_signatures_are_frozen(self) -> None:
        expected = {
            RankSnapshotWriter.upsert_rank_snapshot: (
                "(self, doc_id, snapshot_date, source_channel, rank_in_period, raw_score, score)"
            ),
            RankSnapshotReader.get_snapshot_documents: (
                "(self, snapshot_date, source_channel=None, source_type=None, limit=500)"
            ),
            RankSnapshotReader.get_snapshot_dates: (
                "(self, limit=60, source=None, period=None)"
            ),
            RankSnapshotReader.get_snapshot_source_counts: "(self, snapshot_date)",
            RankSnapshotReader.get_snapshot_doc_ids: (
                "(self, snapshot_date, source_channel=None)"
            ),
            RankSnapshotAdminWriter.delete_snapshots_by_channel: (
                "(self, snapshot_date, source_channel)"
            ),
        }
        for method, signature in expected.items():
            with self.subTest(method=method.__name__):
                self.assertEqual(str(_without_annotations(method)), signature)

    def test_period_channel_mapping_is_frozen(self) -> None:
        self.assertEqual(
            SNAPSHOT_PERIOD_CHANNELS["github"]["daily"],
            ("github_trending_daily", "github_hot_daily", "github_fallback"),
        )
        self.assertEqual(
            SNAPSHOT_PERIOD_CHANNELS["arxiv"]["monthly"],
            ("huggingface_monthly_html",),
        )
        self.assertEqual(SNAPSHOT_PERIOD_CHANNELS["news"], {"daily": ("techmeme_daily_rss",)})
        self.assertEqual(SNAPSHOT_PERIOD_CHANNELS["x"], {"daily": ("x_daily_watchlist",)})


if __name__ == "__main__":
    unittest.main()
