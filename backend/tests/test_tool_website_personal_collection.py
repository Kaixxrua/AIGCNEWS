from __future__ import annotations

import sys
import unittest
from unittest.mock import MagicMock, patch

# Some older test modules leave a minimal langchain_core stub in sys.modules.
# Remove it so this module can import the real message classes during discovery.
_langchain_core = sys.modules.get("langchain_core")
if _langchain_core is not None and not hasattr(_langchain_core, "__path__"):
    sys.modules.pop("langchain_core", None)
    sys.modules.pop("langchain_core.documents", None)

from backend.app.services.ingestion.project_taxonomy import (
    PROMPT_VERSION,
    EnrichmentResult,
    extract_message_text,
)
from backend.app.services.ingestion.tool_website_enricher import ToolWebsiteEnricher
from backend.app.services.ingestion.tool_website_fetcher import ToolWebsiteMetadata


class ToolWebsiteEnricherTests(unittest.TestCase):
    def setUp(self) -> None:
        self.metadata = ToolWebsiteMetadata(
            canonical_url="https://gptsakura.com/",
            normalized_url="https://gptsakura.com/",
            normalized_url_hash="url-hash",
            domain="gptsakura.com",
            title="GPT Sakura",
            description="AI 工具网站",
            image_url="",
            raw_metadata={},
            source_fingerprint="source-fingerprint",
        )
        self.enrichment = EnrichmentResult(
            category_slug="models_infra",
            category_name="模型与基础设施",
            subcategory_slug="model_platforms",
            subcategory_name="模型平台",
            description_zh="提供 AI 模型相关服务。",
            description_en="Provides practical access to AI model services.",
            tags=["模型服务"],
            tags_en=["Model service"],
            confidence=0.9,
        )
        self.db = MagicMock()
        self.db.get_runtime_provider_setting.return_value = {}
        self.db.get_tool_website_by_hash.return_value = {"id": 9, "visibility": "private"}
        self.db.upsert_tool_website.return_value = {"id": 9}
        self.db.get_tool_website_item.return_value = {"website_id": 9}
        with patch(
            "backend.app.services.ingestion.tool_website_enricher._model_metadata",
            return_value={},
        ):
            self.enricher = ToolWebsiteEnricher(self.db)

    def _add(self):
        with patch(
            "backend.app.services.ingestion.tool_website_enricher.fetch_tool_website_metadata",
            return_value=self.metadata,
        ):
            return self.enricher.add_and_enrich(
                "gptsakura.com",
                added_by_user_id=7,
                visibility="private",
            )

    def test_private_duplicate_without_enrichment_runs_enrichment(self) -> None:
        self.db.get_tool_website_enrichment.return_value = None
        self.enricher._enrich_one = MagicMock(return_value=self.enrichment)

        result = self._add()

        self.enricher._enrich_one.assert_called_once_with(self.metadata)
        self.db.upsert_tool_website_enrichment.assert_called_once()
        payload = self.db.upsert_tool_website_enrichment.call_args.args[0]
        self.assertEqual(payload["description_en"], self.enrichment.description_en)
        self.assertFalse(result["duplicate"])
        self.assertEqual(result["item"]["website_id"], 9)
        self.assertFalse(self.db.upsert_tool_website.call_args.kwargs["update_existing"])

    def test_private_duplicate_with_failed_enrichment_retries(self) -> None:
        self.db.get_tool_website_enrichment.return_value = {
            "status": "failed",
            "source_fingerprint": self.metadata.source_fingerprint,
            "prompt_version": PROMPT_VERSION,
        }
        self.enricher._enrich_one = MagicMock(return_value=self.enrichment)

        result = self._add()

        self.enricher._enrich_one.assert_called_once_with(self.metadata)
        self.db.upsert_tool_website_enrichment.assert_called_once()
        self.assertFalse(result["duplicate"])

    def test_private_duplicate_with_current_successful_enrichment_skips_llm(self) -> None:
        self.db.get_tool_website_enrichment.return_value = {
            "status": "succeeded",
            "source_fingerprint": self.metadata.source_fingerprint,
            "prompt_version": PROMPT_VERSION,
        }
        self.enricher._enrich_one = MagicMock()

        result = self._add()

        self.enricher._enrich_one.assert_not_called()
        self.db.upsert_tool_website_enrichment.assert_not_called()
        self.assertTrue(result["duplicate"])
        self.assertFalse(self.db.upsert_tool_website.call_args.kwargs["update_existing"])

    def test_private_duplicate_enrichment_failure_keeps_added_website(self) -> None:
        self.db.get_tool_website_enrichment.return_value = None
        self.enricher._enrich_one = MagicMock(side_effect=RuntimeError("model failed"))

        result = self._add()

        self.db.mark_tool_website_enrichment_failed.assert_called_once()
        self.db.upsert_tool_website_enrichment.assert_not_called()
        self.assertTrue(result["enrichment_failed"])
        self.assertEqual(result["item"]["website_id"], 9)

    def test_enrich_one_accepts_plain_string_content(self) -> None:
        self.enricher._llm = MagicMock()
        self.enricher._llm.invoke.return_value.content = (
            '{"category_slug":"models_infra",'
            '"subcategory_slug":"model_management",'
            '"description_zh":"提供 AI 模型相关服务。",'
            '"description_en":"Provides practical access to AI model services.",'
            '"tags_zh":["模型服务"],"tags_en":["Model service"],"confidence":0.9}'
        )

        result = self.enricher._enrich_one(self.metadata)

        self.assertEqual(result.category_slug, "models_infra")
        self.assertEqual(result.subcategory_slug, "model_management")
        self.assertEqual(result.description_en, "Provides practical access to AI model services.")
        self.assertEqual(result.tags, ["模型服务"])
        self.assertEqual(result.tags_en, ["Model service"])

    def test_enrich_one_accepts_anthropic_thinking_and_text_blocks(self) -> None:
        self.enricher._llm = MagicMock()
        self.enricher._llm.invoke.return_value.content = [
            {"type": "thinking", "thinking": '{"ignore":"reasoning"}'},
            {
                "type": "text",
                "text": (
                    '{"category_slug":"models_infra",'
                    '"subcategory_slug":"model_management",'
                    '"description_zh":"提供 AI 模型相关服务。",'
                    '"tags_zh":["模型服务"],"tags_en":["Model service"],"confidence":0.9}'
                ),
            },
        ]

        result = self.enricher._enrich_one(self.metadata)

        self.assertEqual(result.category_slug, "models_infra")
        self.assertEqual(result.subcategory_slug, "model_management")
        self.assertEqual(result.tags_en, ["Model service"])

    def test_bilingual_tag_backfill_dry_run_advances_without_model_or_writes(self) -> None:
        self.db.list_tool_websites_needing_bilingual_tags.return_value = [
            {"website_id": 9}, {"website_id": 12},
        ]
        self.enricher._enrich_one = MagicMock()

        result = self.enricher.backfill_bilingual_tags(
            after_website_id=3, limit=2, dry_run=True,
        )

        self.assertEqual(result["status"], "dry_run")
        self.assertEqual(result["next_cursor"], 12)
        self.assertTrue(result["has_more"])
        self.enricher._enrich_one.assert_not_called()
        self.db.update_tool_website_system_tags.assert_not_called()

    def test_bilingual_tag_backfill_failure_preserves_existing_enrichment(self) -> None:
        self.db.list_tool_websites_needing_bilingual_tags.return_value = [{
            "website_id": 9,
            "canonical_url": self.metadata.canonical_url,
            "domain": self.metadata.domain,
            "title": self.metadata.title,
            "description": self.metadata.description,
            "source_fingerprint": self.metadata.source_fingerprint,
        }]
        self.enricher._enrich_one = MagicMock(side_effect=RuntimeError("model failed"))

        result = self.enricher.backfill_bilingual_tags(limit=1)

        self.assertEqual(result["status"], "partial")
        self.db.update_tool_website_system_tags.assert_not_called()
        self.db.mark_tool_website_enrichment_failed.assert_not_called()

    def test_extract_message_text_supports_object_blocks_and_ignores_thinking(self) -> None:
        class ContentBlock:
            def __init__(self, block_type: str, text: str = "") -> None:
                self.type = block_type
                self.text = text

        message = MagicMock()
        message.content = [
            ContentBlock("thinking", '{"ignore":"reasoning"}'),
            ContentBlock("text", '{"category_slug":"models_infra",'),
            "\"confidence\":0.9}",
        ]

        self.assertEqual(
            extract_message_text(message),
            '{"category_slug":"models_infra","confidence":0.9}',
        )
