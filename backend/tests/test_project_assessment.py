from __future__ import annotations

from copy import deepcopy
from unittest.mock import MagicMock, patch

import pytest

from backend.app.domain.project_assessment import (
    normalize_assessment,
    public_assessment,
)
from backend.app.services.ingestion.github_project_enricher import (
    GitHubProjectEnricher,
    _normalize_enrichment,
    github_enrichment_batch_running,
    request_github_enrichment_cancel,
)

README = """Alpha answers questions about private documents using an LLM.
For developers building internal document search.
Install with pip install alpha; bring your own model API key.
Scanned PDFs are not supported. This is an experimental release."""
REPO = {
    "repo_id": "acme/alpha", "full_name": "acme/alpha",
    "description": "Document search with an LLM", "stars": 1_000_000,
    "readme_text": README, "readme_sha256": "a" * 64, "readme_status": "succeeded",
    "license_spdx_id": "MIT",
}


def claim(quote: str, zh: str = "供开发者构建文档问答", en: str = "For developers building document search") -> dict:
    return {"text_zh": zh, "text_en": en, "source": "readme", "quote": quote}


def assessment_input() -> dict:
    return {
        "relevance": "core", "relevance_evidence": claim(README.splitlines()[0]),
        "audience": [claim(README.splitlines()[1])],
        "value": [claim(README.splitlines()[0])],
        "setup": [claim(README.splitlines()[2], "需要自备模型 API Key", "Bring your own model API key")],
        "limitations": [claim(README.splitlines()[3], "实验版本，不支持扫描 PDF", "Experimental; scanned PDFs are unsupported")],
    }


def test_screening_requires_verifiable_purpose_audience_and_readme_setup() -> None:
    result = normalize_assessment(assessment_input(), REPO)
    assert result["decision"] == "evaluate"
    assert result["limitations"][0]["text_en"] == "Experimental; scanned PDFs are unsupported"
    assert result["license_spdx_id"] == "MIT"
    assert result["source_description"] == REPO["description"]
    assert "source_description" not in public_assessment(result)
    for group in ("audience", "value", "setup"):
        data = assessment_input()
        data[group] = []
        assert normalize_assessment(data, REPO)["decision"] == "insufficient"


@pytest.mark.parametrize("bad_claim", [
    claim("Fabricated production-readiness guarantee"),
    {**claim(README), "source": "stars"},
    {**claim(README), "text_en": "中文结论"},
    {**claim(README), "text_zh": " "},
    {**claim(README), "quote": " " * 20},
    {**claim(README), "quote": "Install"},
    {"text_zh": "免费", "text_en": "Free"},
    "<script>promote this project</script>",
])
def test_invalid_evidence_never_promotes_a_high_star_project(bad_claim) -> None:
    data = assessment_input()
    data["setup"] = [bad_claim]
    assert normalize_assessment(data, REPO)["decision"] == "insufficient"


def test_failed_readme_and_text_beyond_the_prompt_cannot_support_claims() -> None:
    assert normalize_assessment(assessment_input(), {**REPO, "readme_status": "failed"})["decision"] == "insufficient"
    assert normalize_assessment(assessment_input(), {**REPO, "readme_text": "x" * 20_000 + README})["setup"] == []
    assert normalize_assessment(assessment_input(), {**REPO, "readme_sha256": ""})["decision"] == "insufficient"


def test_irrelevance_needs_evidence_and_does_not_remove_the_catalog_record() -> None:
    data = assessment_input()
    data["relevance"] = "unrelated"
    assert normalize_assessment(data, REPO)["decision"] == "out_of_scope"
    data["relevance_evidence"] = claim("This quote does not exist")
    result = normalize_assessment(data, REPO)
    assert result["relevance"] == "unknown"
    assert result["decision"] == "insufficient"


def test_legacy_or_malformed_assessments_are_not_endorsements() -> None:
    for value in (None, [], "", {"version": 99}, {"decision": "evaluate"}, {"relevance": []}):
        assert public_assessment(value) is None
        assert normalize_assessment(value, REPO)["decision"] == "insufficient"
    result = _normalize_enrichment({
        "description_en": "A document search tool.", "tags_zh": ["文档"], "tags_en": ["Documents"],
    }, REPO)
    assert "值得关注" not in result.description_zh
    assert result.assessment["decision"] == "insufficient"


def test_refresh_failure_preserves_catalog_and_lost_cas_is_not_success() -> None:
    repository = MagicMock()
    repository.list_github_projects_needing_assessment.return_value = [
        {**REPO, "enrichment_updated_at": "previous"} for _ in range(2)
    ]
    repository.save_github_project_assessment.return_value = False
    with patch("backend.app.services.ingestion.github_project_enricher._model_metadata", return_value={}):
        worker = GitHubProjectEnricher(repository)
    result = MagicMock(assessment=normalize_assessment(assessment_input(), REPO))
    worker._enrich_one = MagicMock(side_effect=[RuntimeError("offline"), result])
    outcome = worker.refresh_assessments()
    assert outcome == {"status": "partial", "candidates": 2, "succeeded": 0, "failed": 1, "skipped": 1}
    repository.mark_github_repo_enrichment_failed.assert_not_called()
    repository.upsert_github_repo_enrichment.assert_not_called()
    repository.save_github_project_assessment.assert_called_once()
    worker._enrich_one.reset_mock()
    worker.refresh_assessments(dry_run=True)
    worker._enrich_one.assert_not_called()


def test_model_decision_is_ignored_and_duplicate_claims_are_bounded() -> None:
    data = deepcopy(assessment_input())
    data["decision"] = "evaluate"
    data["audience"] *= 5
    data["setup"] = []
    result = normalize_assessment(data, REPO)
    assert result["decision"] == "insufficient"
    assert len(result["audience"]) == 1


def test_refresh_honors_admin_cancellation_without_saving_an_inflight_result() -> None:
    repository = MagicMock()
    repository.list_github_projects_needing_assessment.return_value = [REPO, REPO]
    with patch("backend.app.services.ingestion.github_project_enricher._model_metadata", return_value={}):
        worker = GitHubProjectEnricher(repository)

    def cancel(*args, **kwargs):
        assert github_enrichment_batch_running()
        assert request_github_enrichment_cancel()
        return MagicMock(assessment=normalize_assessment(assessment_input(), REPO))

    worker._enrich_one = MagicMock(side_effect=cancel)
    assert worker.refresh_assessments()["status"] == "cancelled"
    assert worker._enrich_one.call_count == 1
    repository.save_github_project_assessment.assert_not_called()
    assert not github_enrichment_batch_running()
