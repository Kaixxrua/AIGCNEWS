from __future__ import annotations

import math
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from typing import Sequence

from backend.app.repositories.project_catalog import ProjectLexicalCandidate


@dataclass(frozen=True)
class ProjectCandidateSearchResult:
    lexical_repo_ids: tuple[str, ...]
    semantic_repo_ids: tuple[str, ...]


def rank_legacy_project_candidate_ids(
    lexical_repo_ids: Sequence[str],
    semantic_repo_ids: Sequence[str],
    *,
    rank_constant: int = 60,
    limit: int = 200,
) -> list[str]:
    scores: dict[str, float] = {}
    best_rank: dict[str, int] = {}
    for weight, ranking in (
        (0.45, lexical_repo_ids),
        (0.55, semantic_repo_ids),
    ):
        seen: set[str] = set()
        for rank, raw_repo_id in enumerate(ranking, start=1):
            repo_id = str(raw_repo_id or "").strip()
            if not repo_id or repo_id in seen:
                continue
            seen.add(repo_id)
            scores[repo_id] = scores.get(repo_id, 0.0) + weight / (rank_constant + rank)
            best_rank[repo_id] = min(best_rank.get(repo_id, rank), rank)
    return sorted(
        scores,
        key=lambda repo_id: (-scores[repo_id], best_rank[repo_id], repo_id),
    )[:limit]


def rank_v2_project_candidate_ids(
    strict_candidates: Sequence[ProjectLexicalCandidate],
    relaxed_candidates: Sequence[ProjectLexicalCandidate],
    semantic_repo_ids: Sequence[str],
    *,
    exact_repo_id: str = "",
    rank_constant: int = 60,
    limit: int = 200,
    adoption_stars: Mapping[str, int] | None = None,
    adoption_weight: float = 0.0,
) -> list[str]:
    strict_ids = {candidate.repo_id.strip() for candidate in strict_candidates}
    scores: dict[str, float] = {}
    best_rank: dict[str, int] = {}
    coverage: dict[str, int] = {}
    strength: dict[str, int] = {}
    profile_score: dict[str, int] = {}
    artifact_mismatch: dict[str, bool] = {}
    rankings = (
        (0.45, [(candidate.repo_id, candidate) for candidate in strict_candidates]),
        (0.15, [(candidate.repo_id, candidate) for candidate in relaxed_candidates]),
        (0.40, [(repo_id, None) for repo_id in semantic_repo_ids]),
    )
    for weight, ranking in rankings:
        seen: set[str] = set()
        for rank, (raw_repo_id, candidate) in enumerate(ranking, start=1):
            repo_id = str(raw_repo_id or "").strip()
            if not repo_id or repo_id in seen:
                continue
            seen.add(repo_id)
            scores[repo_id] = scores.get(repo_id, 0.0) + weight / (rank_constant + rank)
            best_rank[repo_id] = min(best_rank.get(repo_id, rank), rank)
            if candidate is not None:
                coverage[repo_id] = max(coverage.get(repo_id, 0), candidate.term_coverage)
                strength[repo_id] = max(strength.get(repo_id, 0), candidate.match_strength)
                profile_score[repo_id] = max(profile_score.get(repo_id, 0), candidate.profile_score)
                artifact_mismatch[repo_id] = candidate.artifact_mismatch
    # 采用度压舱石：只对拟合 lane 已选出的候选加分，fame 无法单飞入榜。
    # log 压缩 + 相对候选集最大值归一，让 10 万星元老从 lane 位次噪声里被救回，
    # 而权重上限保证多 lane 拟合冠军不被罢黜。
    if adoption_weight > 0 and isinstance(adoption_stars, Mapping):
        eligible = [
            (repo_id, int(stars))
            for raw_repo_id, stars in adoption_stars.items()
            if (repo_id := str(raw_repo_id or "").strip()) in scores
            and isinstance(stars, (int, float))
            and int(stars) > 0
        ]
        if eligible:
            denominator = math.log1p(max(stars for _, stars in eligible))
            if denominator > 0:
                for repo_id, stars in eligible:
                    scores[repo_id] += adoption_weight * (math.log1p(stars) / denominator)
    normalized_exact = exact_repo_id.strip().casefold()
    return sorted(
        scores,
        key=lambda repo_id: (
            0 if normalized_exact and repo_id.casefold() == normalized_exact else 1,
            0 if repo_id in strict_ids else 1,
            artifact_mismatch.get(repo_id, False),
            -profile_score.get(repo_id, 0),
            -scores[repo_id],
            -strength.get(repo_id, 0),
            -coverage.get(repo_id, 0),
            best_rank[repo_id],
            repo_id,
        ),
    )[:limit]


RELEVANCE_WEIGHT = 2.0
POPULARITY_WEIGHT = 1.0


def popularity_key(weekly_star_growth: int, stars: int) -> int:
    """长期热度：(1+近 7 日星增)·(1+总星数)，即 log1p 之和的整数单调等价。

    整数比较在 Python 与 Go 两侧逐位一致，不受 log 实现的末位误差影响。
    """
    return (1 + max(int(weekly_star_growth), 0)) * (1 + max(int(stars), 0))


def order_candidates_by_popularity(
    repo_ids: Sequence[str],
    popularity: Mapping[str, tuple[int, int]],
    *,
    exact_repo_id: str = "",
    pinned_repo_ids: Collection[str] = (),
    rank_constant: int = 60,
) -> list[str]:
    """语义搜索展示序：相关性为主、长期热度为辅的位次融合。

    传入顺序即 lane 融合的相关性序。popularity 为 {repo_id: (近 7 日
    星增, 总星数)}，按 popularity_key 降序得到热度位次；展示序按
    RELEVANCE_WEIGHT/(k+相关性位次) + POPULARITY_WEIGHT/(k+热度位次)
    降序，同分回落相关性位次。相关性占 2/3，当红但只沾边的候选抬不进
    首页，相关且有人气的项目则前移；7 日窗口跨过零点，不随当天首轮
    指标的有无而整体翻转。

    精确命中钉在榜首；pinned_repo_ids 是全部严格查询词都命中的候选，
    不受页大小影响，钉在精确命中之后、
    融合序之上，相互间保持相关性序。
    """
    ordered_ids = [str(repo_id) for repo_id in repo_ids]
    fusion_rank = {repo_id: index for index, repo_id in enumerate(ordered_ids)}
    normalized_exact = exact_repo_id.strip().casefold()
    pinned = {str(repo_id) for repo_id in pinned_repo_ids}

    def _popularity_of(repo_id: str) -> int:
        value = popularity.get(repo_id)
        if not isinstance(value, (tuple, list)) or len(value) != 2:
            return popularity_key(0, 0)
        weekly_growth, stars = value
        return popularity_key(
            int(weekly_growth) if isinstance(weekly_growth, (int, float)) else 0,
            int(stars) if isinstance(stars, (int, float)) else 0,
        )

    popularity_rank = {
        repo_id: rank
        for rank, repo_id in enumerate(
            sorted(ordered_ids, key=lambda repo_id: (-_popularity_of(repo_id), fusion_rank[repo_id])),
            start=1,
        )
    }

    def _sort_key(repo_id: str) -> tuple[int, float, int]:
        if normalized_exact and repo_id.casefold() == normalized_exact:
            return (0, 0.0, fusion_rank[repo_id])
        if repo_id in pinned:
            return (1, 0.0, fusion_rank[repo_id])
        blended = RELEVANCE_WEIGHT / (rank_constant + fusion_rank[repo_id] + 1) + POPULARITY_WEIGHT / (
            rank_constant + popularity_rank[repo_id]
        )
        return (2, -blended, fusion_rank[repo_id])

    return sorted(ordered_ids, key=_sort_key)
