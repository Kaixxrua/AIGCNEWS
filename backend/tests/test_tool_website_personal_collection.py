from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from backend.app.core.config import settings
from backend.app.domain.project_taxonomy import (
    PROMPT_VERSION,
    EnrichmentResult,
    extract_message_text,
)
from backend.app.services.ingestion.tool_website_enricher import ToolWebsiteEnricher
from backend.app.services.ingestion.tool_website_fetcher import ToolWebsiteMetadata
from backend.app.services.ingestion.website_content_moderation import (
    ModerationUnavailableError,
    ModerationVerdict,
)


class ToolWebsiteEnricherTests(unittest.TestCase):
    def setUp(self) -> None:
        self.metadata = ToolWebsiteMetadata(
            canonical_url="https://example.com/",
            normalized_url="https://example.com/",
            normalized_url_hash="url-hash",
            domain="example.com",
            title="Example AI Tools",
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
            self.moderator = MagicMock()
            self.moderator.moderate.return_value = ModerationVerdict(is_adult=False)
            self.enricher = ToolWebsiteEnricher(self.db, moderator=self.moderator)
        moderation_enabled = patch.object(settings, "tool_website_moderation_enabled", True)
        moderation_enabled.start()
        self.addCleanup(moderation_enabled.stop)

    def _add(self):
        with patch(
            "backend.app.services.ingestion.tool_website_enricher.fetch_tool_website_metadata",
            return_value=self.metadata,
        ):
            return self.enricher.add_and_enrich(
                "example.com",
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

    def test_add_and_enrich_blocks_adult_website_before_enrichment(self) -> None:
        self.db.get_tool_website_enrichment.return_value = None
        self.moderator.moderate.return_value = ModerationVerdict(
            is_adult=True, reason="成人视频平台"
        )
        self.enricher._enrich_one = MagicMock()

        result = self._add()

        self.assertTrue(result["blocked"])
        self.assertEqual(result["reason"], "成人视频平台")
        self.enricher._enrich_one.assert_not_called()
        self.db.mark_tool_website_enrichment_blocked.assert_called_once()
        blocked_kwargs = self.db.mark_tool_website_enrichment_blocked.call_args.kwargs
        self.assertEqual(blocked_kwargs["prompt_version"], f"{PROMPT_VERSION}-blocked")
        self.assertEqual(blocked_kwargs["reason"], "成人视频平台")
        self.assertEqual(
            blocked_kwargs["source_fingerprint"], self.metadata.source_fingerprint
        )
        self.db.get_tool_website_item.assert_not_called()
        self.db.upsert_tool_website_enrichment.assert_not_called()

    def test_add_and_enrich_short_circuits_previously_blocked_website(self) -> None:
        self.db.get_tool_website_enrichment.return_value = {
            "status": "blocked",
            "error_msg": "检测到成人或不适宜内容",
            "source_fingerprint": self.metadata.source_fingerprint,
            "prompt_version": f"{PROMPT_VERSION}-blocked",
        }
        self.enricher._enrich_one = MagicMock()

        result = self._add()

        self.assertTrue(result["blocked"])
        self.assertEqual(result["reason"], "检测到成人或不适宜内容")
        self.moderator.moderate.assert_not_called()
        self.enricher._enrich_one.assert_not_called()
        self.db.mark_tool_website_enrichment_blocked.assert_not_called()

    def test_add_and_enrich_propagates_moderation_unavailable_without_blocked_row(
        self,
    ) -> None:
        self.db.get_tool_website_enrichment.return_value = None
        self.moderator.moderate.side_effect = ModerationUnavailableError(
            "内容审核服务暂时不可用，请稍后重试"
        )
        self.enricher._enrich_one = MagicMock()

        with self.assertRaises(ModerationUnavailableError):
            self._add()

        self.enricher._enrich_one.assert_not_called()
        self.db.mark_tool_website_enrichment_blocked.assert_not_called()
        self.db.upsert_tool_website_enrichment.assert_not_called()

    def _add_manual(self, **overrides):
        kwargs = {
            "url": "https://example.com/",
            "title": "Example",
            "description_zh": "示例说明",
            "category_slug": "productivity_tools",
            "subcategory_slug": "",
            "tags": ["效率"],
            "added_by_user_id": 7,
            "visibility": "private",
        }
        kwargs.update(overrides)
        return self.enricher.add_manual(**kwargs)

    def test_add_manual_blocks_adult_content_without_writes(self) -> None:
        self.moderator.moderate.return_value = ModerationVerdict(
            is_adult=True, reason="成人交友平台"
        )

        result = self._add_manual()

        self.assertTrue(result["blocked"])
        self.assertEqual(result["reason"], "成人交友平台")
        self.db.upsert_tool_website.assert_not_called()
        self.db.upsert_tool_website_enrichment.assert_not_called()

    def test_add_manual_propagates_moderation_unavailable_without_writes(self) -> None:
        self.moderator.moderate.side_effect = ModerationUnavailableError(
            "内容审核服务暂时不可用，请稍后重试"
        )

        with self.assertRaises(ModerationUnavailableError):
            self._add_manual()

        self.db.upsert_tool_website.assert_not_called()
        self.db.upsert_tool_website_enrichment.assert_not_called()

    def test_add_manual_clean_content_overwrites_previous_block(self) -> None:
        self.db.get_tool_website_enrichment.return_value = {
            "status": "blocked",
            "error_msg": "检测到成人或不适宜内容",
        }

        result = self._add_manual()

        self.assertFalse(result.get("blocked", False))
        self.assertTrue(
            self.db.upsert_tool_website.call_args.kwargs["update_existing"]
        )
        payload = self.db.upsert_tool_website_enrichment.call_args.args[0]
        self.assertTrue(str(payload["prompt_version"]).endswith("-manual"))
        self.assertEqual(payload["status"], "succeeded")

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
                    '"description_en":"Provides practical access to AI model services.",'
                    '"tags_zh":["模型服务"],"tags_en":["Model service"],"confidence":0.9}'
                ),
            },
        ]

        result = self.enricher._enrich_one(self.metadata)

        self.assertEqual(result.category_slug, "models_infra")
        self.assertEqual(result.subcategory_slug, "model_management")
        self.assertEqual(result.description_en, "Provides practical access to AI model services.")
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
