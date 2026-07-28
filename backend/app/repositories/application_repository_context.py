from __future__ import annotations

from threading import Lock

from backend.app.repositories.application_repository_factory import (
    ApplicationRepositories,
)


_lock = Lock()
_repositories: ApplicationRepositories | None = None


def configure_application_repositories(
    repositories: ApplicationRepositories | None,
) -> None:
    global _repositories
    with _lock:
        _repositories = repositories


def get_configured_application_repositories() -> ApplicationRepositories:
    with _lock:
        repositories = _repositories
    if repositories is None:
        raise RuntimeError("Application repositories are not configured")
    return repositories
