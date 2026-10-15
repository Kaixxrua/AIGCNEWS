"""Retired assessments remain stored but cannot filter or populate the catalog."""

from __future__ import annotations

import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api import routes_github_projects
from backend.app.api.dependencies import get_project_catalog_query_service
from backend.app.repositories.postgres_project_catalog import PostgresProjectCatalogRepository
from backend.app.repositories.postgres_project_enrichment_repository import PostgresGitHubProjectEnrichmentRepository
from backend.app.services.project_catalog.query_service import ProjectCatalogQueryService
from backend.tests.postgres_test_safety import postgres_test_sandbox
from backend.tests.test_project_assessment import LEGACY_ASSESSMENT, README, REPO


def test_retired_assessments_preserve_catalog_search_and_stored_history() -> None:
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
        payload = {
            "category_slug": "rag_knowledge", "category_name": "知识库",
            "description_zh": "文档问答", "description_en": "Document search with an LLM",
            "source_fingerprint": "input", "prompt_version": "test",
            "assessment": LEGACY_ASSESSMENT,
        }
        for name in ("ready", "legacy", "other", "gone"):
            writer.upsert_github_repo_enrichment({**payload, "repo_id": f"acme/{name}"})
        with database.transaction() as connection:
            # Even an old caller supplying assessment data must not populate it.
            assert connection.execute(
                "SELECT count(*) AS count FROM github_repo_enrichments WHERE assessment_json IS NOT NULL"
            ).fetchone()["count"] == 0
            connection.execute(
                "UPDATE github_repo_enrichments SET assessment_json=%s::jsonb WHERE repo_id='acme/ready'",
                (json.dumps(LEGACY_ASSESSMENT),),
            )
            connection.execute("UPDATE github_repo_candidates SET availability_status='not_found' WHERE repo_id='acme/gone'")

        page = catalog.list_projects(source="github", scope="screened")
        assert page == catalog.list_projects(source="github", scope="all")
        assert page["total"] == 4
        assert all(item["assessment"] is None for item in page["items"])
        for query in ("find_lexical_candidate_repo_ids", "find_lexical_candidate_lanes"):
            search = getattr(catalog, query)
            assert search(q="document", scope="screened") == search(q="document", scope="all")
        assert len(catalog.find_lexical_candidate_repo_ids(q="document", scope="screened")) == 4

        app = FastAPI()
        app.include_router(routes_github_projects.router, prefix="/api")
        app.dependency_overrides[get_project_catalog_query_service] = lambda: ProjectCatalogQueryService(
            repository_factory=lambda: catalog,
        )
        client = TestClient(app)
        response = client.get("/api/projects?scope=screened&sort=name")
        assert response.status_code == 200
        assert response.json() == client.get("/api/projects?scope=all&sort=name").json()
        assert response.json()["scope"] == "all"
        assert response.json()["total"] == 4
        assert all(item["assessment"] is None for item in response.json()["items"])

        # Ordinary enrichment must preserve history without reviving it.
        writer.upsert_github_repo_enrichment({**payload, "repo_id": "acme/ready", "assessment": None})
        with database.transaction() as connection:
            stored = connection.execute(
                "SELECT assessment_json FROM github_repo_enrichments WHERE repo_id='acme/ready'"
            ).fetchone()["assessment_json"]
        assert stored == LEGACY_ASSESSMENT
        assert all(item["assessment"] is None for item in catalog.list_projects()["items"])
