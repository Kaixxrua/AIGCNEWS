from __future__ import annotations

from typing import Any

from backend.app.repositories.postgres_project_write_repository import (
    PostgresProjectWriteRepository,
)
from backend.app.repositories.project_write_repository import (
    GitHubProjectRecommendationRepository,
    UserProjectCollectionRepository,
)


def test_postgres_write_adapter_exposes_both_project_write_protocols() -> None:
    expected = set(UserProjectCollectionRepository.__dict__) | set(
        GitHubProjectRecommendationRepository.__dict__
    )
    expected = {name for name in expected if not name.startswith("_")}

    assert expected.issubset(dir(PostgresProjectWriteRepository))


def test_collection_read_helpers_preserve_catalog_aggregate_filters() -> None:
    repository = PostgresProjectWriteRepository.__new__(PostgresProjectWriteRepository)
    calls: list[tuple[str, dict[str, Any]]] = []

    def list_projects(**kwargs: Any) -> dict[str, Any]:
        calls.append(("projects", kwargs))
        return {"items": []}

    def get_project_categories(**kwargs: Any) -> dict[str, Any]:
        calls.append(("categories", kwargs))
        return {"items": []}

    repository.list_projects = list_projects  # type: ignore[method-assign]
    repository.get_project_categories = get_project_categories  # type: ignore[method-assign]

    assert repository.list_user_project_collection(user_id=7, source="website") == {
        "items": []
    }
    assert repository.get_user_project_categories(
        user_id=7, source="github", min_stars=900, enriched_only=False
    ) == {"items": []}
    assert calls == [
        (
            "projects",
            {"user_id": 7, "favorites_only": True, "source": "website"},
        ),
        (
            "categories",
            {
                "source": "github",
                "min_stars": 900,
                "enriched_only": False,
                "user_id": 7,
                "favorites_only": True,
            },
        ),
    ]
