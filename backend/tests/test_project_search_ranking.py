from backend.app.services.project_search_ranking import (
    ProjectCandidateSearchResult,
    rank_legacy_project_candidate_ids,
)


def test_candidate_search_result_is_immutable_and_typed_by_lane() -> None:
    result = ProjectCandidateSearchResult(
        lexical_repo_ids=("owner/lexical",),
        semantic_repo_ids=("owner/semantic",),
    )

    assert result.lexical_repo_ids == ("owner/lexical",)
    assert result.semantic_repo_ids == ("owner/semantic",)


def test_legacy_candidate_ranker_preserves_frozen_ordering() -> None:
    ranked = rank_legacy_project_candidate_ids(
        ["owner/lexical", "owner/shared"],
        ["owner/semantic", "owner/shared"],
    )

    assert ranked == ["owner/shared", "owner/semantic", "owner/lexical"]


def test_legacy_candidate_ranker_normalizes_and_deduplicates_each_ranking() -> None:
    ranked = rank_legacy_project_candidate_ids(
        [" owner/a ", "owner/a", ""],
        ["owner/b", "owner/b", "owner/a"],
    )

    assert ranked == ["owner/a", "owner/b"]


def test_legacy_candidate_ranker_applies_limit_after_stable_tie_break() -> None:
    ranked = rank_legacy_project_candidate_ids(
        ["owner/b", "owner/a"],
        [],
        rank_constant=0,
        limit=1,
    )

    assert ranked == ["owner/b"]
