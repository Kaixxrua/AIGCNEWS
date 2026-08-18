from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from backend.app.services.ingestion.website_content_moderation import (
    ModerationUnavailableError,
)
from backend.app.services.personal_projects import (
    InvalidPersonalProjectRequest,
    PersonalProjectNotFound,
    PersonalProjectsService,
    PersonalWebsiteOperationFailed,
    WebsiteContentBlockedError,
)


class PersonalProjectsServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.collection = MagicMock()
        self.enrichment = MagicMock()
        self.enricher = MagicMock()
        self.collection.get_personal_website_quota_usage.return_value = {
            "used": 0,
            "reset_at": None,
        }
        self.service = PersonalProjectsService(
            collection=self.collection,
            enrichment=self.enrichment,
            enricher_factory=lambda repository: self.enricher,
        )

    async def test_collection_reads_propagate_owner_and_preserve_source_defaults(
        self,
    ) -> None:
        collection = self.collection
        collection.list_user_project_collection.return_value = {"items": [], "total": 0}
        collection.get_user_project_categories.return_value = {"items": [], "total": 0}
        collection.get_user_project_tags.return_value = {"items": [], "total": 0}

        await self.service.list_collection(user_id=7, source="all", page=2, min_stars=500)
        await self.service.get_categories(user_id=7, source="website", min_stars=500)
        await self.service.get_tags(user_id=7, source="all", enriched_only=True)

        collection.list_user_project_collection.assert_called_once_with(
            user_id=7,
            source="github",
            page=2,
            min_stars=500,
        )
        collection.get_user_project_categories.assert_called_once_with(
            user_id=7,
            source="website",
            min_stars=500,
        )
        collection.get_user_project_tags.assert_called_once_with(
            user_id=7,
            source="github",
            enriched_only=True,
        )

    async def test_favorite_errors_are_mapped_without_losing_owner(self) -> None:
        collection = self.collection
        collection.add_project_favorite.side_effect = LookupError("GitHub 项目不存在")

        with self.assertRaises(PersonalProjectNotFound) as not_found:
            await self.service.add_favorite(user_id=7, source="github", repo_id="owner/repo")
        self.assertIn("GitHub 项目不存在", str(not_found.exception))

        collection.add_project_favorite.assert_called_once_with(
            user_id=7,
            source="github",
            repo_id="owner/repo",
            website_id=None,
        )

        collection.remove_project_favorite.side_effect = ValueError("website_id 不能为空")
        with self.assertRaises(InvalidPersonalProjectRequest) as invalid:
            await self.service.remove_favorite(user_id=7, source="website")
        self.assertIn("website_id 不能为空", str(invalid.exception))

    async def test_free_website_quota_is_enforced_after_duplicate_resolution(self) -> None:
        self.enricher.add_and_enrich.return_value = {
            "duplicate": True,
            "item": {"website_id": 42},
        }
        self.collection.link_user_tool_website.return_value = {"user_added": True}
        self.collection.get_tool_website_item_for_user.return_value = {"website_id": 42}

        result = await self.service.add_tool_website(user_id=7, url="https://example.com")

        self.assertTrue(result["duplicate"])
        self.collection.get_personal_website_quota_usage.assert_not_called()
        self.collection.link_user_tool_website.assert_called_once_with(
            user_id=7,
            website_id=42,
            added_via="existing",
            quota_enabled=True,
            quota_limit=5,
            quota_window_seconds=86400,
        )

    async def test_member_website_quota_is_unlimited(self) -> None:
        self.enricher.add_and_enrich.return_value = {
            "duplicate": False,
            "item": {"website_id": 42},
        }
        self.collection.link_user_tool_website.return_value = {"user_added": True}
        self.collection.get_tool_website_item_for_user.return_value = {"website_id": 42}

        await self.service.add_tool_website(
            user_id=7,
            url="https://example.com",
            membership_tier="member",
        )

        self.collection.get_personal_website_quota_usage.assert_not_called()
        self.assertIsNone(
            self.collection.link_user_tool_website.call_args.kwargs["quota_limit"]
        )

    async def test_website_quota_projection_reports_remaining(self) -> None:
        self.collection.get_personal_website_quota_usage.return_value = {
            "used": 3,
            "reset_at": "2026-08-19T00:00:00+00:00",
        }

        quota = await self.service.get_website_quota(user_id=7)

        self.assertEqual(quota["remaining"], 2)
        self.assertFalse(quota["unlimited"])
        self.assertEqual(quota["window_seconds"], 86400)

    async def test_auto_website_sequences_enrichment_link_and_owner_projection(
        self,
    ) -> None:
        collection = self.collection
        enricher = self.enricher
        events: list[str] = []
        enricher.add_and_enrich.side_effect = lambda *args, **kwargs: (
            events.append("enrich")
            or {"duplicate": True, "item": {"website_id": 42, "title": "global"}}
        )
        collection.link_user_tool_website.side_effect = lambda **kwargs: (
            events.append("link")
            or {"user_added": True, "user_added_at": "now"}
        )
        collection.get_tool_website_item_for_user.side_effect = lambda **kwargs: (
            events.append("project")
            or {"website_id": 42, "title": "owner"}
        )

        result = await self.service.add_tool_website(user_id=7, url=" https://example.com ")

        self.assertEqual(events, ["enrich", "link", "project"])
        enricher.add_and_enrich.assert_called_once_with(
            "https://example.com",
            added_by_user_id=7,
            visibility="private",
        )
        collection.link_user_tool_website.assert_called_once_with(
            user_id=7,
            website_id=42,
            added_via="existing",
            quota_enabled=True,
            quota_limit=5,
            quota_window_seconds=86400,
        )
        collection.get_tool_website_item_for_user.assert_called_once_with(
            user_id=7,
            website_id=42,
        )
        self.assertEqual(
            result,
            {
                "status": "succeeded",
                "message": "工具网站已存在，已加入我的收藏。",
                "duplicate": True,
                "item": {
                    "website_id": 42,
                    "title": "owner",
                    "user_added": True,
                    "user_added_at": "now",
                },
            },
        )

    async def test_auto_website_preserves_best_effort_enrichment_message(self) -> None:
        collection = self.collection
        enricher = self.enricher
        enricher.add_and_enrich.return_value = {
            "duplicate": False,
            "enrichment_failed": True,
            "item": {"website_id": 42},
        }
        collection.link_user_tool_website.return_value = {"user_added": True}
        collection.get_tool_website_item_for_user.return_value = {"website_id": 42}

        result = await self.service.add_tool_website(user_id=7, url="https://example.com")

        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(
            result["message"],
            "工具网站已添加到我的收藏，AI 分类服务暂时不可用，可稍后编辑分类。",
        )

    async def test_auto_website_blocked_raises_and_skips_link(self) -> None:
        collection = self.collection
        self.enricher.add_and_enrich.return_value = {
            "duplicate": False,
            "blocked": True,
            "reason": "成人视频平台",
        }

        with self.assertRaises(WebsiteContentBlockedError) as blocked:
            await self.service.add_tool_website(user_id=7, url="https://adult.example")
        self.assertIn("无法收藏该网址", str(blocked.exception))

        collection.link_user_tool_website.assert_not_called()
        collection.get_tool_website_item_for_user.assert_not_called()

    async def test_auto_website_moderation_unavailable_maps_to_operation_failure(
        self,
    ) -> None:
        collection = self.collection
        self.enricher.add_and_enrich.side_effect = ModerationUnavailableError(
            "内容审核服务暂时不可用，请稍后重试"
        )

        with self.assertRaises(PersonalWebsiteOperationFailed) as failed:
            await self.service.add_tool_website(user_id=7, url="https://example.com")
        self.assertIn("审核服务暂时不可用", str(failed.exception))

        collection.link_user_tool_website.assert_not_called()

    async def test_manual_website_blocked_raises_and_writes_nothing(self) -> None:
        collection = self.collection
        self.enricher.add_manual.return_value = {
            "duplicate": False,
            "blocked": True,
            "reason": "成人交友平台",
        }

        with self.assertRaises(WebsiteContentBlockedError) as blocked:
            await self.service.add_tool_website_manual(
                user_id=7,
                url="https://adult.example",
                title="Adult",
                description_zh="成人内容说明",
                category_slug="other",
                subcategory_slug="",
                tags=[],
            )
        self.assertIn("无法收藏该网址", str(blocked.exception))

        collection.link_user_tool_website.assert_not_called()
        collection.upsert_user_tool_website_override.assert_not_called()

    async def test_manual_website_moderation_unavailable_maps_to_operation_failure(
        self,
    ) -> None:
        collection = self.collection
        self.enricher.add_manual.side_effect = ModerationUnavailableError(
            "内容审核服务暂时不可用，请稍后重试"
        )

        with self.assertRaises(PersonalWebsiteOperationFailed) as failed:
            await self.service.add_tool_website_manual(
                user_id=7,
                url="https://example.com",
                title="Example",
                description_zh="示例说明",
                category_slug="other",
                subcategory_slug="",
                tags=[],
            )
        self.assertIn("审核服务暂时不可用", str(failed.exception))

        collection.link_user_tool_website.assert_not_called()
        collection.upsert_user_tool_website_override.assert_not_called()

    async def test_manual_website_sequences_link_before_owner_override(self) -> None:
        collection = self.collection
        enricher = self.enricher
        events: list[str] = []
        enricher.add_manual.side_effect = lambda **kwargs: (
            events.append("manual")
            or {"duplicate": False, "item": {"website_id": 42}}
        )
        collection.link_user_tool_website.side_effect = lambda **kwargs: (
            events.append("link") or {"user_added": True}
        )
        collection.upsert_user_tool_website_override.side_effect = lambda payload: (
            events.append("override") or dict(payload)
        )

        result = await self.service.add_tool_website_manual(
            user_id=7,
            url=" https://example.com ",
            title=" Example ",
            description_zh=" 示例说明 ",
            category_slug="unknown",
            subcategory_slug="",
            tags=["标签", "标签", "第二", "第三", "第四", "第五"],
        )

        self.assertEqual(events, ["manual", "link", "override"])
        enricher.add_manual.assert_called_once_with(
            url="https://example.com",
            title="Example",
            description_zh="示例说明",
            category_slug="unknown",
            subcategory_slug="",
            tags=["标签", "标签", "第二", "第三", "第四", "第五"],
            added_by_user_id=7,
            visibility="private",
        )
        payload = collection.upsert_user_tool_website_override.call_args.args[0]
        self.assertEqual(payload["user_id"], 7)
        self.assertEqual(payload["website_id"], 42)
        self.assertEqual(payload["category_slug"], "other")
        self.assertEqual(payload["tags"], ["标签", "第二", "第三", "第四"])
        self.assertIs(result["item"]["user_added"], True)

    async def test_manual_link_failure_stops_override_but_does_not_compensate_enrichment(
        self,
    ) -> None:
        collection = self.collection
        enricher = self.enricher
        enricher.add_manual.return_value = {
            "duplicate": False,
            "item": {"website_id": 42},
        }
        collection.link_user_tool_website.side_effect = RuntimeError("database unavailable")

        with self.assertRaises(PersonalWebsiteOperationFailed) as failed:
            await self.service.add_tool_website_manual(
                user_id=7,
                url="https://example.com",
                title="Example",
                description_zh="示例说明",
                category_slug="other",
                subcategory_slug="other_misc",
                tags=[],
            )
        self.assertIn("工具网站手动添加失败：database unavailable", str(failed.exception))

        enricher.add_manual.assert_called_once()
        collection.upsert_user_tool_website_override.assert_not_called()
        collection.unlink_user_tool_website.assert_not_called()

    async def test_update_and_remove_are_owner_scoped(self) -> None:
        collection = self.collection
        collection.upsert_user_tool_website_override.side_effect = LookupError(
            "该工具网站不在你的收藏夹中"
        )

        with self.assertRaises(PersonalProjectNotFound) as not_found:
            await self.service.update_tool_website(
                user_id=7,
                website_id=42,
                title="Example",
                description="Description",
                description_zh="示例说明",
                category_slug="other",
                subcategory_slug="other_misc",
                tags=[],
                image_url="",
            )
        self.assertIn("不在你的收藏夹", str(not_found.exception))

        payload = collection.upsert_user_tool_website_override.call_args.args[0]
        self.assertEqual(payload["user_id"], 7)
        self.assertEqual(payload["website_id"], 42)

        collection.unlink_user_tool_website.return_value = True
        self.assertIs(await self.service.remove_tool_website(user_id=7, website_id=42), True)
        collection.unlink_user_tool_website.assert_called_once_with(
            user_id=7,
            website_id=42,
        )
