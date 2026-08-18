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
    scores: dict[str, float] = {}
    best_rank: dict[str, int] = {}
    coverage: dict[str, int] = {}
    strength: dict[str, int] = {}
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
            -scores[repo_id],
            -strength.get(repo_id, 0),
            -coverage.get(repo_id, 0),
            best_rank[repo_id],
            repo_id,
        ),
    )[:limit]


def order_candidates_by_heat(
    repo_ids: Sequence[str],
    heat: Mapping[str, tuple[float, int, int]],
    *,
    exact_repo_id: str = "",
    pinned_repo_ids: Collection[str] = (),
) -> list[str]:
    """语义搜索展示序：精确命中钉在榜首，其余按 hot_score(v5) 热度降序。

    lane 融合只决定候选名单；展示序默认让位给热度算法分，避免向量噪声
    把当红项目埋在长尾相似项后面。热度口径与列表 hot 排序一致：
    hot_score → daily_star_growth → stars 依次兜底；三项全同（含无当日
    指标的项目）回落到传入的融合位次，保证确定性排序。

    例外：pinned_repo_ids（调用方仅在 strict lane 一页放得下时传入）是
    全部严格查询词都命中的确定答案，钉在精确命中之后、热度重排之上，
    相互间保持融合拟合序——避免唯一正确答案被当红噪声罢黜（典型如
    "windows screenshot tool" 的 strict 独苗被无关热项压出首页）。
    """
    ordered_ids = [str(repo_id) for repo_id in repo_ids]
    fusion_rank = {repo_id: index for index, repo_id in enumerate(ordered_ids)}
    normalized_exact = exact_repo_id.strip().casefold()
    pinned = {str(repo_id) for repo_id in pinned_repo_ids}

    def _heat_of(repo_id: str) -> tuple[float, int, int]:
        value = heat.get(repo_id)
        if not isinstance(value, (tuple, list)) or len(value) != 3:
            return (0.0, 0, 0)
        hot_score, daily_growth, stars = value
        return (
            float(hot_score) if isinstance(hot_score, (int, float)) else 0.0,
            int(daily_growth) if isinstance(daily_growth, (int, float)) else 0,
            int(stars) if isinstance(stars, (int, float)) else 0,
        )

    def _sort_key(repo_id: str) -> tuple[int, tuple[float, int, int], int]:
        if normalized_exact and repo_id.casefold() == normalized_exact:
            return (0, (0.0, 0, 0), fusion_rank[repo_id])
        if repo_id in pinned:
            # pinned 之间不看热度，保持融合拟合序
            return (1, (0.0, 0, 0), fusion_rank[repo_id])
        return (
            2,
            tuple(-component for component in _heat_of(repo_id)),
            fusion_rank[repo_id],
        )

    return sorted(ordered_ids, key=_sort_key)
