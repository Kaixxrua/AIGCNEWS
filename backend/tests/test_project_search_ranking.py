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


def test_v2_ranker_without_adoption_map_keeps_fit_only_order() -> None:
    strict = [ProjectLexicalCandidate("owner/fit", "strict", term_coverage=3)]
    relaxed = [ProjectLexicalCandidate("owner/veteran", "relaxed", term_coverage=1)]
    semantic = ["owner/veteran"]
    expected = rank_v2_project_candidate_ids(strict, relaxed, semantic)

    assert rank_v2_project_candidate_ids(strict, relaxed, semantic, adoption_stars=None) == expected
    assert rank_v2_project_candidate_ids(strict, relaxed, semantic, adoption_stars={}) == expected


def test_v2_ranker_adoption_bonus_rescues_buried_high_star_candidate() -> None:
    strict = [
        ProjectLexicalCandidate(f"owner/fit-{index}", "strict", term_coverage=3)
        for index in range(4)
    ]
    relaxed = [
        *(
            ProjectLexicalCandidate(f"owner/fit-{index}", "relaxed", term_coverage=2)
            for index in range(4)
        ),
        *(
            ProjectLexicalCandidate(f"owner/filler-{index}", "relaxed", term_coverage=1)
            for index in range(15)
        ),
        ProjectLexicalCandidate("owner/veteran", "relaxed", term_coverage=1),
    ]
    semantic = [f"owner/sem-{index}" for index in range(29)] + ["owner/veteran"]
    stars = {
        "owner/veteran": 106_000,
        "owner/ghost": 500_000,
        **{f"owner/fit-{index}": 20_000 for index in range(4)},
        **{f"owner/sem-{index}": 1_000 for index in range(29)},
        **{f"owner/filler-{index}": 800 for index in range(15)},
    }

    baseline = rank_v2_project_candidate_ids(strict, relaxed, semantic)
    boosted = rank_v2_project_candidate_ids(
        strict, relaxed, semantic, adoption_stars=stars, adoption_weight=0.006
    )

    # 采用度只重排既有候选，绝不把拟合 lane 之外的项目拉进榜单
    assert set(boosted) == set(baseline)
    assert "owner/ghost" not in boosted
    # 双 lane 拟合冠军不被采用度罢黜
    assert boosted[0] == baseline[0] == "owner/fit-0"
    # 基线里被埋到第 8 位的高星元老被救回前列
    assert baseline.index("owner/veteran") >= 6
    assert boosted.index("owner/veteran") < baseline.index("owner/veteran")
    assert boosted.index("owner/veteran") <= 4


def test_v2_ranker_adoption_bonus_rejects_non_mapping_input() -> None:
    strict = [ProjectLexicalCandidate("owner/fit", "strict", term_coverage=3)]
    semantic = ["owner/veteran"]
    expected = rank_v2_project_candidate_ids(strict, [], semantic)

    assert rank_v2_project_candidate_ids(
        strict, [], semantic, adoption_stars=object(), adoption_weight=0.006
    ) == expected
