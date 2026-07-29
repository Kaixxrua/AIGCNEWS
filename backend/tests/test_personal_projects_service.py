from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from backend.app.services.personal_projects import (
    InvalidPersonalProjectRequest,
    PersonalProjectNotFound,
    PersonalProjectsService,
    PersonalWebsiteOperationFailed,
)


@pytest.fixture
def collection() -> MagicMock:
    return MagicMock()


@pytest.fixture
def enrichment() -> MagicMock:
    return MagicMock()


@pytest.fixture
def enricher() -> MagicMock:
    return MagicMock()


@pytest.fixture
def service(
    collection: MagicMock,
    enrichment: MagicMock,
    enricher: MagicMock,
) -> PersonalProjectsService:
    return PersonalProjectsService(
        collection=collection,
        enrichment=enrichment,
        enricher_factory=lambda repository: enricher,
    )


@pytest.mark.anyio
async def test_collection_reads_propagate_owner_and_preserve_source_defaults(
    service: PersonalProjectsService,
    collection: MagicMock,
) -> None:
    collection.list_user_project_collection.return_value = {"items": [], "total": 0}
    collection.get_user_project_categories.return_value = {"items": [], "total": 0}
    collection.get_user_project_tags.return_value = {"items": [], "total": 0}

    await service.list_collection(user_id=7, source="all", page=2, min_stars=500)
    await service.get_categories(user_id=7, source="website", min_stars=500)
    await service.get_tags(user_id=7, source="all", enriched_only=True)

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


@pytest.mark.anyio
async def test_favorite_errors_are_mapped_without_losing_owner(
    service: PersonalProjectsService,
    collection: MagicMock,
) -> None:
    collection.add_project_favorite.side_effect = LookupError("GitHub 项目不存在")

    with pytest.raises(PersonalProjectNotFound, match="GitHub 项目不存在"):
        await service.add_favorite(user_id=7, source="github", repo_id="owner/repo")

    collection.add_project_favorite.assert_called_once_with(
        user_id=7,
        source="github",
        repo_id="owner/repo",
        website_id=None,
    )

    collection.remove_project_favorite.side_effect = ValueError("website_id 不能为空")
    with pytest.raises(InvalidPersonalProjectRequest, match="website_id 不能为空"):
        await service.remove_favorite(user_id=7, source="website")


@pytest.mark.anyio
async def test_auto_website_sequences_enrichment_link_and_owner_projection(
    service: PersonalProjectsService,
    collection: MagicMock,
    enricher: MagicMock,
) -> None:
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

    result = await service.add_tool_website(user_id=7, url=" https://example.com ")

    assert events == ["enrich", "link", "project"]
    enricher.add_and_enrich.assert_called_once_with(
        "https://example.com",
        added_by_user_id=7,
        visibility="private",
    )
    collection.link_user_tool_website.assert_called_once_with(
        user_id=7,
        website_id=42,
        added_via="existing",
    )
    collection.get_tool_website_item_for_user.assert_called_once_with(
        user_id=7,
        website_id=42,
    )
    assert result == {
        "status": "succeeded",
        "message": "工具网站已存在，已加入我的收藏。",
        "duplicate": True,
        "item": {
            "website_id": 42,
            "title": "owner",
            "user_added": True,
            "user_added_at": "now",
        },
    }


@pytest.mark.anyio
async def test_auto_website_preserves_best_effort_enrichment_message(
    service: PersonalProjectsService,
    collection: MagicMock,
    enricher: MagicMock,
) -> None:
    enricher.add_and_enrich.return_value = {
        "duplicate": False,
        "enrichment_failed": True,
        "item": {"website_id": 42},
    }
    collection.link_user_tool_website.return_value = {"user_added": True}
    collection.get_tool_website_item_for_user.return_value = {"website_id": 42}

    result = await service.add_tool_website(user_id=7, url="https://example.com")

    assert result["status"] == "succeeded"
    assert result["message"] == (
        "工具网站已添加到我的收藏，AI 分类服务暂时不可用，可稍后编辑分类。"
    )


@pytest.mark.anyio
async def test_manual_website_sequences_link_before_owner_override(
    service: PersonalProjectsService,
    collection: MagicMock,
    enricher: MagicMock,
) -> None:
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

    result = await service.add_tool_website_manual(
        user_id=7,
        url=" https://example.com ",
        title=" Example ",
        description_zh=" 示例说明 ",
        category_slug="unknown",
        subcategory_slug="",
        tags=["标签", "标签", "第二", "第三", "第四", "第五"],
    )

    assert events == ["manual", "link", "override"]
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
    assert payload["user_id"] == 7
    assert payload["website_id"] == 42
    assert payload["category_slug"] == "other"
    assert payload["tags"] == ["标签", "第二", "第三", "第四"]
    assert result["item"]["user_added"] is True


@pytest.mark.anyio
async def test_manual_link_failure_stops_override_but_does_not_compensate_enrichment(
    service: PersonalProjectsService,
    collection: MagicMock,
    enricher: MagicMock,
) -> None:
    enricher.add_manual.return_value = {
        "duplicate": False,
        "item": {"website_id": 42},
    }
    collection.link_user_tool_website.side_effect = RuntimeError("database unavailable")

    with pytest.raises(
        PersonalWebsiteOperationFailed,
        match="工具网站手动添加失败：database unavailable",
    ):
        await service.add_tool_website_manual(
            user_id=7,
            url="https://example.com",
            title="Example",
            description_zh="示例说明",
            category_slug="other",
            subcategory_slug="other_misc",
            tags=[],
        )

    enricher.add_manual.assert_called_once()
    collection.upsert_user_tool_website_override.assert_not_called()
    collection.unlink_user_tool_website.assert_not_called()


@pytest.mark.anyio
async def test_update_and_remove_are_owner_scoped(
    service: PersonalProjectsService,
    collection: MagicMock,
) -> None:
    collection.upsert_user_tool_website_override.side_effect = LookupError(
        "该工具网站不在你的收藏夹中"
    )

    with pytest.raises(PersonalProjectNotFound, match="不在你的收藏夹"):
        await service.update_tool_website(
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

    payload = collection.upsert_user_tool_website_override.call_args.args[0]
    assert payload["user_id"] == 7
    assert payload["website_id"] == 42

    collection.unlink_user_tool_website.return_value = True
    assert await service.remove_tool_website(user_id=7, website_id=42) is True
    collection.unlink_user_tool_website.assert_called_once_with(
        user_id=7,
        website_id=42,
    )
