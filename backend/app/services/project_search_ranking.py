from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


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
