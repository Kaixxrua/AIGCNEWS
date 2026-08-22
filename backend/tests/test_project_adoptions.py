from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api import routes_github_projects
from backend.app.api.dependencies import get_project_adoption_service
from backend.app.core.postgres_migrations import discover_migrations
from backend.app.repositories.postgres_project_adoption_repository import (
    PostgresProjectAdoptionRepository,
)
from backend.app.services.mcp.contracts import (
    TOOL_INPUT_MODELS,
    SubmitProjectAdoptionInput,
)
from backend.app.services.project_adoptions import (
    ProjectAdoptionService,
    adoption_rate,
)


class FakeCursor:
    def __init__(self, connection: "FakeConnection") -> None:
        self.connection = connection

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *_: Any) -> None:
        return None

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> None:
        normalized = " ".join(sql.split())
        self.connection.executions.append((normalized, params))
        self.connection.rows = (
            self.connection.planned.pop(0) if self.connection.planned else []
        )

    def fetchone(self) -> dict[str, Any] | None:
        return self.connection.rows.pop(0) if self.connection.rows else None

    def fetchall(self) -> list[dict[str, Any]]:
        rows = list(self.connection.rows)
        self.connection.rows.clear()
        return rows


class FakeConnection:
    def __init__(self, planned: list[list[dict[str, Any]]] | None = None) -> None:
        self.planned = list(planned or [])
        self.rows: list[dict[str, Any]] = []
        self.executions: list[tuple[str, tuple[Any, ...] | None]] = []

    def cursor(self) -> FakeCursor:
        return FakeCursor(self)


class FakeDatabase:
    """PostgresDatabaseLifecycle 最小替身：transaction() 直返假连接。"""

    def __init__(self, planned: list[list[dict[str, Any]]] | None = None) -> None:
        self.connection = FakeConnection(planned)

    def transaction(self) -> "FakeTransaction":
        return FakeTransaction(self.connection)


class FakeTransaction:
    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection

    def __enter__(self) -> FakeConnection:
        return self.connection

    def __exit__(self, *_: Any) -> None:
        return None


class FakeAdoptionRepository:
    def __init__(self) -> None:
        self.receipts: list[dict[str, Any]] = []

    def record_project_adoption(self, receipt: dict[str, Any]) -> dict[str, Any]:
        self.receipts.append(dict(receipt))
        return {
            "id": len(self.receipts),
            "created_at": "2026-08-17T10:00:00+00:00",
            **receipt,
        }

    def get_project_adoption_stats(self, *, since_days: int = 30) -> dict[str, Any]:
        window: dict[str, int] = {}
        for receipt in self.receipts:
            window[receipt["decision"]] = window.get(receipt["decision"], 0) + 1
        return {"window_days": since_days, "window": window, "total": dict(window)}


class MigrationContractTests(unittest.TestCase):
    def test_0046_is_discovered_and_idempotent(self) -> None:
        migrations = discover_migrations()
        match = [m for m in migrations if m.version == 46]
        self.assertEqual(len(match), 1)
        sql = match[0].sql
        self.assertIn("CREATE TABLE IF NOT EXISTS project_adoptions", sql)
        self.assertIn("CREATE INDEX IF NOT EXISTS", sql)
        for column in ("project_full_name", "decision", "reason", "query", "source", "created_at"):
            self.assertIn(column, sql)


class PostgresRepositoryContractTests(unittest.TestCase):
    def test_record_inserts_bounded_fields_and_returns_row(self) -> None:
        database = FakeDatabase(
            [
                [
                    {
                        "id": 7,
                        "project_full_name": "owner/repo",
                        "decision": "adopted",
                        "reason": "fits",
                        "query": "workflow engine",
                        "source": "mcp",
                        "created_at": "2026-08-17T10:00:00+00:00",
                    }
                ]
            ]
        )
        repository = PostgresProjectAdoptionRepository(database)  # type: ignore[arg-type]

        row = repository.record_project_adoption(
            {
                "project_full_name": "owner/repo",
                "decision": "adopted",
                "reason": "fits",
                "query": "workflow engine",
                "source": "mcp",
            }
        )

        self.assertEqual(row["id"], 7)
        sql, params = database.connection.executions[0]
        self.assertIn("INSERT INTO project_adoptions", sql)
        self.assertEqual(params, ("owner/repo", "adopted", "fits", "workflow engine", "mcp"))

    def test_record_defaults_optional_fields(self) -> None:
        database = FakeDatabase([[{"id": 1}]])
        repository = PostgresProjectAdoptionRepository(database)  # type: ignore[arg-type]
        repository.record_project_adoption(
            {"project_full_name": "owner/repo", "decision": "declined"}
        )
        _, params = database.connection.executions[0]
        self.assertEqual(params, ("owner/repo", "declined", "", "", "mcp"))

    def test_stats_groups_by_decision_and_clamps_window(self) -> None:
        database = FakeDatabase(
            [
                [
                    {"decision": "adopted", "count": 3},
                    {"decision": "declined", "count": 1},
                ],
                [
                    {"decision": "adopted", "count": 9},
                ],
            ]
        )
        repository = PostgresProjectAdoptionRepository(database)  # type: ignore[arg-type]

        stats = repository.get_project_adoption_stats(since_days=9999)

        self.assertEqual(stats["window_days"], 365)
        self.assertEqual(stats["window"], {"adopted": 3, "declined": 1})
        self.assertEqual(stats["total"], {"adopted": 9})
        first_sql, first_params = database.connection.executions[0]
        self.assertIn("GROUP BY decision", first_sql)
        self.assertEqual(first_params, (365,))


class ServiceTests(unittest.TestCase):
    def test_record_rejects_unknown_decision_before_touching_repository(self) -> None:
        repository = FakeAdoptionRepository()
        service = ProjectAdoptionService(repository_factory=lambda: repository)

        with self.assertRaises(ValueError):
            service.record({"project_full_name": "owner/repo", "decision": "maybe"})
        self.assertEqual(repository.receipts, [])

    def test_record_attaches_stats_with_rates(self) -> None:
        repository = FakeAdoptionRepository()
        service = ProjectAdoptionService(repository_factory=lambda: repository)

        recorded = service.record(
            {"project_full_name": "owner/repo", "decision": "adopted"}
        )

        self.assertEqual(recorded["stats"]["window"], {"adopted": 1})
        self.assertEqual(recorded["stats"]["window_adoption_rate"], 1.0)

    def test_adoption_rate_math(self) -> None:
        self.assertEqual(adoption_rate({}), 0.0)
        self.assertEqual(adoption_rate({"adopted": 1, "declined": 3}), 0.25)
        self.assertEqual(adoption_rate({"reference_only": 2}), 0.0)


class McpContractTests(unittest.TestCase):
    """契约层（contracts.py）输入模型钉住；入站 catalog/tools 已随 W6-U4 退役。"""

    def test_submit_adoption_registered_in_tool_input_models(self) -> None:
        self.assertIn("submit_project_adoption", TOOL_INPUT_MODELS)

    def test_input_model_validation(self) -> None:
        parsed = SubmitProjectAdoptionInput.model_validate(
            {"project_full_name": "owner/repo", "decision": "adopted"}
        )
        self.assertEqual(parsed.source, "mcp")
        self.assertEqual(parsed.reason, "")
        with self.assertRaises(Exception):
            SubmitProjectAdoptionInput.model_validate(
                {"project_full_name": "owner/repo", "decision": "maybe"}
            )
        with self.assertRaises(Exception):
            SubmitProjectAdoptionInput.model_validate(
                {"project_full_name": "owner/repo", "decision": "adopted", "extra": 1}
            )


class RestRouteTests(unittest.TestCase):
    def _client(self, repository: FakeAdoptionRepository) -> TestClient:
        app = FastAPI()
        app.include_router(routes_github_projects.router, prefix="/api")
        app.dependency_overrides[get_project_adoption_service] = (
            lambda: ProjectAdoptionService(repository_factory=lambda: repository)
        )
        return TestClient(app)

    def test_post_adoption_returns_receipt_and_stats(self) -> None:
        repository = FakeAdoptionRepository()
        client = self._client(repository)

        response = client.post(
            "/api/projects/adoptions",
            json={
                "project_full_name": "owner/repo",
                "decision": "adopted",
                "reason": "battle-tested",
                "query": "workflow engine",
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["receipt"]["decision"], "adopted")
        self.assertEqual(payload["stats"]["total_adoption_rate"], 1.0)
        self.assertEqual(repository.receipts[0]["source"], "rest")

        stats = client.get("/api/projects/adoptions/stats")
        self.assertEqual(stats.status_code, 200)
        self.assertEqual(stats.json()["window"], {"adopted": 1})

    def test_post_adoption_rejects_bad_decision(self) -> None:
        client = self._client(FakeAdoptionRepository())
        response = client.post(
            "/api/projects/adoptions",
            json={"project_full_name": "owner/repo", "decision": "maybe"},
        )
        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()
