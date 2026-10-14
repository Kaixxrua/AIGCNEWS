"""Exercise migration, persisted assessments and real catalog selection together."""

from __future__ import annotations

import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api import routes_github_projects
from backend.app.api.dependencies import get_project_catalog_query_service
from backend.app.domain.project_assessment import normalize_assessment
from backend.app.repositories.postgres_project_catalog import PostgresProjectCatalogRepository
from backend.app.repositories.postgres_project_enrichment_repository import PostgresGitHubProjectEnrichmentRepository
from backend.app.services.project_catalog.query_service import ProjectCatalogQueryService
from backend.tests.postgres_test_safety import postgres_test_sandbox
from backend.tests.test_project_assessment import README, REPO, assessment_input


def test_assessment_roundtrip_screening_freshness_and_compare_and_swap() -> None:
    with postgres_test_sandbox() as sandbox:
        database = sandbox.database
        catalog = PostgresProjectCatalogRepository(database)
        writer = PostgresGitHubProjectEnrichmentRepository(database)
        with database.transaction() as connection:
            for name in ("ready", "legacy", "other", "gone"):
                repo_id = f"acme/{name}"
                connection.execute(
                    "INSERT INTO github_repo_candidates (repo_id,full_name,description,stars,license_spdx_id)"
                    " VALUES (%s,%s,%s,900,'MIT')",
                    (repo_id, repo_id, REPO["description"]),
                )
                connection.execute(
                    "INSERT INTO github_project_semantic_sources"
                    " (repo_id,readme_text,readme_sha256,readme_status,updated_at)"
                    " VALUES (%s,%s,%s,'succeeded','now')",
                    (repo_id, README, REPO["readme_sha256"]),
                )
        for name in ("ready", "legacy", "other", "gone"):
            data = assessment_input()
            if name == "other":
                data["relevance"] = "unrelated"
            writer.upsert_github_repo_enrichment({
                "repo_id": f"acme/{name}", "category_slug": "rag_knowledge", "category_name": "知识库",
                "description_zh": "文档问答", "description_en": "Document search with an LLM",
                "source_fingerprint": "input", "prompt_version": "test",
                "assessment": normalize_assessment(data, REPO) if name != "legacy" else None,
            })
        with database.transaction() as connection:
            connection.execute("UPDATE github_repo_candidates SET availability_status='not_found' WHERE repo_id='acme/gone'")
        page = catalog.list_projects(source="github", scope="screened")
        assert page["total"] == 1
        assert page["items"][0]["repo_id"] == "acme/ready"
        assert page["items"][0]["assessment"]["limitations"]
        assert "source_description" not in page["items"][0]["assessment"]
        assert catalog.list_projects(source="github", scope="all")["total"] == 4
        assert catalog.list_projects(source="website", scope="screened")["total"] == 0
        assert catalog.find_lexical_candidate_repo_ids(q="document", scope="screened") == ["acme/ready"]
        lanes = catalog.find_lexical_candidate_lanes(q="document", scope="screened")
        assert [item.repo_id for item in lanes.strict] == ["acme/ready"]
        app = FastAPI()
        app.include_router(routes_github_projects.router, prefix="/api")
        app.dependency_overrides[get_project_catalog_query_service] = lambda: ProjectCatalogQueryService(
            repository_factory=lambda: catalog,
        )
        response = TestClient(app).get("/api/projects?scope=screened")
        assert response.status_code == 200
        assert response.json()["scope"] == "screened"
        assert response.json()["items"][0]["assessment"]["decision"] == "evaluate"
        with database.transaction() as connection:
            connection.execute("UPDATE github_repo_candidates SET license_spdx_id='NOASSERTION' WHERE repo_id='acme/ready'")
        assert catalog.list_projects(source="github", scope="screened")["total"] == 0
        with database.transaction() as connection:
            connection.execute("UPDATE github_repo_candidates SET license_spdx_id='MIT' WHERE repo_id='acme/ready'")
        candidates = writer.list_github_projects_needing_assessment()
        assert [row["repo_id"] for row in candidates] == ["acme/legacy"]
        row = candidates[0]
        assessment = normalize_assessment(assessment_input(), row)
        assert not writer.save_github_project_assessment(
            repo_id=row["repo_id"], assessment=assessment, expected_updated_at="outdated",
        )
        assert writer.save_github_project_assessment(
            repo_id=row["repo_id"], assessment=assessment, expected_updated_at=row["enrichment_updated_at"],
        )
        assert catalog.list_projects(source="github", scope="screened")["total"] == 2
        # A new source invalidates both presentation and selection immediately.
        with database.transaction() as connection:
            connection.execute("UPDATE github_repo_candidates SET description='Changed purpose' WHERE repo_id='acme/ready'")
            connection.execute("UPDATE github_project_semantic_sources SET readme_sha256='new-hash' WHERE repo_id='acme/legacy'")
        assert catalog.list_projects(source="github", scope="screened")["total"] == 0
        items = catalog.list_projects(source="github", scope="all")["items"]
        assert all(item["assessment"] is None for item in items if item["repo_id"] in {"acme/ready", "acme/legacy"})
        # Old/future-format data fails closed, without hiding the project itself.
        with database.transaction() as connection:
            expired = normalize_assessment(assessment_input(), REPO)
            expired["assessed_at"] = "2000-01-01T00:00:00+00:00"
            connection.execute("UPDATE github_repo_enrichments SET assessment_json=%s::jsonb WHERE repo_id='acme/other'", (json.dumps(expired),))
        assert len(writer.list_github_projects_needing_assessment()) == 3
