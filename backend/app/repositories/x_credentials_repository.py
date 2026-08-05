from __future__ import annotations

from typing import Any, Protocol


class XCredentialConflictError(Exception):
    """A unique X credential field conflicts with another row."""


class XCredentialSeeder(Protocol):
    def ensure_seeded_from_env(self) -> None: ...


class XCredentialRepository(XCredentialSeeder, Protocol):
    """Persistence boundary for the X credential pool."""

    def list_x_credentials(self) -> list[dict[str, Any]]: ...

    def get_x_credential(self, credential_id: int) -> dict[str, Any] | None: ...

    def list_enabled_x_credentials(self) -> list[dict[str, Any]]: ...

    def create_x_credential(self, payload: dict[str, Any]) -> dict[str, Any]: ...

    def update_x_credential(
        self, credential_id: int, payload: dict[str, Any]
    ) -> dict[str, Any] | None: ...

    def delete_x_credential(self, credential_id: int) -> bool: ...

    def update_x_credential_test_result(
        self, credential_id: int, result: dict[str, Any]
    ) -> dict[str, Any] | None: ...
