from __future__ import annotations

import inspect
import sys
import types
import unittest
from unittest.mock import MagicMock

_config_name = "backend.app.core.config"
_previous_config = sys.modules.get(_config_name)
_config_stub = types.ModuleType(_config_name)
_config_stub.settings = MagicMock()
sys.modules[_config_name] = _config_stub
try:
    from backend.app.repositories.mysql_repo import MySQLRepository
finally:
    if _previous_config is None:
        sys.modules.pop(_config_name, None)
    else:
        sys.modules[_config_name] = _previous_config


class GitHubProjectMetricProjectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.legacy_source = inspect.getsource(MySQLRepository.list_github_projects)
        self.unified_source = inspect.getsource(MySQLRepository.list_projects)
        self.categories_source = inspect.getsource(MySQLRepository.get_project_categories)

    def _assert_atomic_metric_projection(self, source: str) -> None:
        for field in ("stars", "forks", "watchers", "open_issues"):
            fallback = f"COALESCE(c.{field}, 0)" if field != "open_issues" else "0"
            self.assertIn(
                f"CASE WHEN gm.repo_id IS NOT NULL THEN gm.{field} ELSE {fallback} END AS {field}",
                source,
            )
            self.assertNotIn(f"COALESCE(gm.{field}, c.{field})", source)
        self.assertIn("AND gm.metric_date = %s", source)
        self.assertIn("gm.metric_date AS snapshot_date", source)
        self.assertIn("COALESCE(gm.daily_growth_source, 'unavailable')", source)

    def test_legacy_list_uses_one_atomic_metric_projection(self) -> None:
        self._assert_atomic_metric_projection(self.legacy_source)

    def test_unified_list_uses_one_atomic_metric_projection(self) -> None:
        self._assert_atomic_metric_projection(self.unified_source)

    def test_today_top_fifty_uses_metric_stars_but_candidate_eligibility(self) -> None:
        self.assertIn("WHERE COALESCE(c_top.stars, 0) > %s", self.unified_source)
        self.assertIn("gm_top.stars DESC", self.unified_source)
        self.assertNotIn("c_top.stars DESC", self.unified_source)
        self.assertIn("gm_top.daily_growth_available = 1", self.unified_source)
        self.assertIn("gm_top.daily_star_growth > 0", self.unified_source)

    def test_today_count_matches_top_fifty_metric_tiebreaker(self) -> None:
        self.assertIn("WHERE COALESCE(c_top.stars, 0) > %s", self.categories_source)
        self.assertIn("gm_top.stars DESC", self.categories_source)
        self.assertNotIn("c_top.stars DESC", self.categories_source)
        self.assertIn("gm_top.daily_growth_available = 1", self.categories_source)
        self.assertIn("gm_top.daily_star_growth > 0", self.categories_source)

    def test_sorting_uses_projected_aliases(self) -> None:
        self.assertIn(
            '"hot": "hot_score DESC, daily_star_growth DESC, stars DESC, c.full_name ASC"',
            self.legacy_source,
        )
        self.assertIn('"stars": "stars DESC, forks DESC, c.full_name ASC"', self.legacy_source)
        self.assertIn(
            '"hot": "hot_score DESC, daily_star_growth DESC, stars DESC, full_name ASC"',
            self.unified_source,
        )
        self.assertIn('"stars": "stars DESC, forks DESC, full_name ASC"', self.unified_source)


if __name__ == "__main__":
    unittest.main()
