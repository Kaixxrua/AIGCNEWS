from backend.app.repositories.project_catalog import ProjectLexicalCandidate
from backend.app.services.project_search_ranking import (
    ProjectCandidateSearchResult,
    rank_legacy_project_candidate_ids,
    rank_v2_project_candidate_ids,
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


def test_v2_ranker_accumulates_strict_relaxed_and_semantic_lanes() -> None:
    ranked = rank_v2_project_candidate_ids(
        [
            ProjectLexicalCandidate("owner/strict", "strict", term_coverage=3, match_strength=2),
            ProjectLexicalCandidate("owner/shared", "strict", term_coverage=2, match_strength=1),
        ],
        [
            ProjectLexicalCandidate("owner/relaxed", "relaxed", term_coverage=2, match_strength=2),
            ProjectLexicalCandidate("owner/shared", "relaxed", term_coverage=2, match_strength=1),
        ],
        ["owner/semantic", "owner/shared"],
    )

    assert ranked == [
        "owner/shared",
        "owner/strict",
        "owner/semantic",
        "owner/relaxed",
    ]


def test_v2_ranker_protects_exact_repository_lookup() -> None:
    ranked = rank_v2_project_candidate_ids(
        [ProjectLexicalCandidate("owner/popular", "strict", term_coverage=2, match_strength=3)],
        [ProjectLexicalCandidate("DeusData/codebase-memory-mcp", "relaxed", term_coverage=1, match_strength=1)],
        ["owner/popular"],
        exact_repo_id="deusdata/codebase-memory-mcp",
    )

    assert ranked[0] == "DeusData/codebase-memory-mcp"
