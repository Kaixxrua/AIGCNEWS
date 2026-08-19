from __future__ import annotations

from typing import Any
from unittest import IsolatedAsyncioTestCase
from unittest.mock import MagicMock, patch

from backend.app.repositories.project_catalog import (
    ProjectLexicalCandidate,
    ProjectLexicalCandidateLanes,
)
from backend.app.services import project_discovery


def _lanes(*repo_ids: str) -> ProjectLexicalCandidateLanes:
    return ProjectLexicalCandidateLanes(
        strict=tuple(
            ProjectLexicalCandidate(repo_id, "strict", term_coverage=1, match_strength=0)
            for repo_id in repo_ids
        ),
    )


def _echo_first_candidate_page(**kwargs: Any) -> dict[str, Any]:
    candidate_ids = kwargs["candidate_repo_ids"]
    return {
        "items": [{"full_name": candidate_ids[0], "stars": 100}],
        "total": len(candidate_ids),
    }


class _V2Repository:
    """v2 混合检索的最小仓库替身：lanes、名段钉顶查询与水合页均可断言。"""

    def __init__(
        self,
        *,
        lanes: ProjectLexicalCandidateLanes,
        name_hits: list[str] | Exception,
    ) -> None:
        self.find_lexical_candidate_repo_ids = MagicMock(return_value=[])
        self.find_lexical_candidate_lanes = MagicMock(return_value=lanes)
        if isinstance(name_hits, Exception):
            self.find_repo_ids_by_name_segment = MagicMock(side_effect=name_hits)
        else:
            self.find_repo_ids_by_name_segment = MagicMock(return_value=name_hits)
        self.list_projects = MagicMock(side_effect=_echo_first_candidate_page)


class BareRepoNameExactPinTests(IsolatedAsyncioTestCase):
    """裸仓库名（无 '/'）查询在 v2 策略下的唯一命中钉顶契约。"""

    def setUp(self) -> None:
        patchers = [
            patch.object(project_discovery.settings, "project_ai_search_strategy", "v2"),
            patch.object(project_discovery.settings, "project_semantic_search_enabled", False),
        ]
        for patcher in patchers:
            patcher.start()
            self.addCleanup(patcher.stop)

    async def _search(self, repository: Any, query: str = "pi") -> dict[str, Any]:
        return await project_discovery.search_projects(
            query=query,
            mode="ai",
            repository_factory=lambda: repository,
        )

    async def test_unique_name_segment_hit_is_pinned_above_lane_order(self) -> None:
        # lanes 里 earendil-works/pi 故意排在第二——钉顶必须独立于 lane 位次生效。
        repository = _V2Repository(
            lanes=_lanes("pi-hole/pi-hole", "earendil-works/pi"),
            name_hits=["earendil-works/pi"],
        )

        result = await self._search(repository)

        repository.find_repo_ids_by_name_segment.assert_called_once_with(name="pi", limit=2)
        pinned = repository.list_projects.call_args.kwargs["candidate_repo_ids"][0]
        self.assertEqual(pinned, "earendil-works/pi")
        self.assertEqual(result["items"][0]["full_name"], "earendil-works/pi")

    async def test_ambiguous_name_segment_hits_disable_pin(self) -> None:
        repository = _V2Repository(
            lanes=_lanes("pi-hole/pi-hole", "earendil-works/pi"),
            name_hits=["earendil-works/pi", "other/pi"],
        )

        await self._search(repository)

        # 歧义时保持 lane 融合序，不钉顶
        ordered = repository.list_projects.call_args.kwargs["candidate_repo_ids"]
        self.assertEqual(ordered[0], "pi-hole/pi-hole")

    async def test_name_lookup_failure_degrades_to_plain_ranking(self) -> None:
        repository = _V2Repository(
            lanes=_lanes("pi-hole/pi-hole", "earendil-works/pi"),
            name_hits=RuntimeError("database down"),
        )

        result = await self._search(repository)

        ordered = repository.list_projects.call_args.kwargs["candidate_repo_ids"]
        self.assertEqual(ordered[0], "pi-hole/pi-hole")
        self.assertEqual(result["total"], 2)

    async def test_repository_without_name_lookup_degrades_gracefully(self) -> None:
        class LegacyShapedRepository:
            def __init__(self) -> None:
                self.find_lexical_candidate_repo_ids = MagicMock(return_value=[])
                self.find_lexical_candidate_lanes = MagicMock(
                    return_value=_lanes("pi-hole/pi-hole")
                )
                self.list_projects = MagicMock(side_effect=_echo_first_candidate_page)

        repository = LegacyShapedRepository()
        result = await self._search(repository)

        ordered = repository.list_projects.call_args.kwargs["candidate_repo_ids"]
        self.assertEqual(ordered[0], "pi-hole/pi-hole")
        self.assertEqual(result["total"], 1)

    async def test_owner_slash_repo_query_pins_directly_without_name_lookup(self) -> None:
        repository = _V2Repository(
            lanes=_lanes("pi-hole/pi-hole", "earendil-works/pi"),
            name_hits=[],
        )

        await self._search(repository, query="earendil-works/pi")

        repository.find_repo_ids_by_name_segment.assert_not_called()
        pinned = repository.list_projects.call_args.kwargs["candidate_repo_ids"][0]
        self.assertEqual(pinned, "earendil-works/pi")

    async def test_legacy_strategy_never_calls_name_lookup(self) -> None:
        project_discovery.settings.project_ai_search_strategy = "legacy"

        class LegacyRepository:
            def __init__(self) -> None:
                self.find_lexical_candidate_repo_ids = MagicMock(
                    return_value=["earendil-works/pi"]
                )
                self.find_repo_ids_by_name_segment = MagicMock(return_value=["earendil-works/pi"])
                self.list_projects = MagicMock(side_effect=_echo_first_candidate_page)

        repository = LegacyRepository()
        result = await self._search(repository)

        # legacy 展示序由 SQL 名段层级承载，不应为名段钉顶多打一次查询
        repository.find_repo_ids_by_name_segment.assert_not_called()
        self.assertEqual(result["items"][0]["full_name"], "earendil-works/pi")
