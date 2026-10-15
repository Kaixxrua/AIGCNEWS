"""Retirement contracts: normal enrichment continues without trial assessments."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage

from backend.app.repositories.project_catalog_normalization import normalize_project_row
from backend.app.repositories.project_write_repository import GitHubProjectEnrichmentRepository
from backend.app.services.ingestion.github_project_enricher import GitHubProjectEnricher

README = "For developers building document search with an LLM. Install with pip install alpha."
REPO = {
    "repo_id": "acme/alpha", "full_name": "acme/alpha",
    "description": "Document search with an LLM", "stars": 900,
    "readme_text": README, "readme_sha256": "a" * 64, "readme_status": "succeeded",
    "license_spdx_id": "MIT", "source_fingerprint": "input",
}
_CLAIM = {
    "text_zh": "供开发者构建文档问答", "text_en": "For developers building document search",
    "source": "readme", "quote": README,
}
# Represents a previously valid stored assessment, including internal metadata.
LEGACY_ASSESSMENT = {
    "version": 1, "decision": "evaluate", "relevance": "core",
    "relevance_evidence": _CLAIM, "value": [_CLAIM], "audience": [_CLAIM],
    "setup": [_CLAIM], "limitations": [], "assessed_at": datetime.now(timezone.utc).isoformat(),
    "readme_sha256": REPO["readme_sha256"], "license_spdx_id": "MIT",
    "source_description": REPO["description"],
}


def test_new_project_enrichment_does_not_request_or_save_assessments() -> None:
    repository = MagicMock(spec=GitHubProjectEnrichmentRepository)
    repository.runtime_provider_settings.get_runtime_provider_setting.return_value = {}
    worker = GitHubProjectEnricher(repository)
    worker._llm = MagicMock()
    worker._llm.invoke.return_value = AIMessage(content=json.dumps({
        "category_slug": "rag_knowledge", "subcategory_slug": "knowledge_bases",
        "description_zh": "帮助开发者构建文档问答系统。",
        "description_en": "Helps developers build document search with an LLM.",
        "tags_zh": ["文档问答"], "tags_en": ["Document search"], "confidence": 0.9,
        "assessment": LEGACY_ASSESSMENT,
    }))

    assert worker._enrich_and_store(REPO) is True

    messages = worker._llm.invoke.call_args.args[0]
    assert "assessment" not in messages[0].content
    assert json.loads(messages[1].content)["readme"]["text"] == README
    repository.upsert_github_repo_enrichment.assert_called_once()
    saved = repository.upsert_github_repo_enrichment.call_args.args[0]
    assert saved["status"] == "succeeded"
    assert saved["description_en"] == "Helps developers build document search with an LLM."
    assert saved["tags_en_json"] == '["Document search"]'
    assert "assessment" not in saved
    assert "assessment_json" not in saved
    repository.mark_github_repo_enrichment_failed.assert_not_called()


@pytest.mark.parametrize("field", ["assessment", "assessment_json"])
def test_catalog_hides_legacy_assessments_without_hiding_projects(field: str) -> None:
    result = normalize_project_row({
        "repo_id": "acme/alpha", "full_name": "acme/alpha", "stars": 900,
        field: LEGACY_ASSESSMENT,
    })

    assert result["repo_id"] == "acme/alpha"
    assert result["stars"] == 900
    assert result["assessment"] is None
    assert "assessment_json" not in result
