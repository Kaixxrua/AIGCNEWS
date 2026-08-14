from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from backend.app.domain.project_taxonomy import (
    ENGLISH_LABEL_BY_SLUG,
    WEBSITE_CATEGORY_BY_SLUG,
    WEBSITE_DEFAULT_SUBCATEGORY_BY_CATEGORY,
    WEBSITE_SUBCATEGORY_BY_CATEGORY_SLUG,
    clean_text,
    normalize_subcategory,
)
from backend.app.repositories.project_write_repository import (
    ToolWebsiteEnrichmentRepository,
    UserProjectCollectionRepository,
)
from backend.app.services.ingestion.tool_website_fetcher import ToolWebsiteFetchError
from backend.app.services.ingestion.website_content_moderation import (
    ModerationUnavailableError,
)


class PersonalProjectsError(Exception):
    """Base failure exposed by personal project orchestration."""


class InvalidPersonalProjectRequest(PersonalProjectsError):
    """The requested personal project operation is invalid."""


class PersonalProjectNotFound(PersonalProjectsError):
    """The requested project is unavailable to the collection owner."""


class PersonalWebsiteOperationFailed(PersonalProjectsError):
    """Website ingestion failed after entering the orchestration boundary."""


class WebsiteContentBlockedError(PersonalProjectsError):
    """The website was rejected by adult-content moderation."""


class WebsiteEnricher(Protocol):
    def add_and_enrich(
        self,
        url: str,
        *,
        added_by_user_id: int | None = None,
        visibility: str = "public",
    ) -> dict[str, Any]: ...

    def add_manual(
        self,
        *,
        url: str,
        title: str,
        description_zh: str,
        category_slug: str,
        subcategory_slug: str = "",
        tags: list[str] | None = None,
        added_by_user_id: int | None = None,
        visibility: str = "public",
    ) -> dict[str, Any]: ...


WebsiteEnricherFactory = Callable[[ToolWebsiteEnrichmentRepository], WebsiteEnricher]
ThreadRunner = Callable[..., Awaitable[Any]]


def _default_enricher_factory(
    repository: ToolWebsiteEnrichmentRepository,
) -> WebsiteEnricher:
    from backend.app.services.ingestion.tool_website_enricher import ToolWebsiteEnricher

    return ToolWebsiteEnricher(repository)


def _require_owner(user_id: int) -> int:
    try:
        owner_id = int(user_id)
    except (TypeError, ValueError) as exc:
        raise InvalidPersonalProjectRequest("用户身份无效") from exc
    if owner_id <= 0:
        raise InvalidPersonalProjectRequest("用户身份无效")
    return owner_id


def _normalize_source(source: str, *, default: str = "github") -> str:
    clean_source = (source or default).strip().lower()
    return "website" if clean_source == "website" else "github"


def build_tool_website_override(
    *,
    user_id: int,
    website_id: int,
    title: str,
    description_zh: str,
    category_slug: str,
    subcategory_slug: str,
    tags: list[str],
    description: str = "",
    description_en: str = "",
    image_url: str = "",
) -> dict[str, Any]:
    owner_id = _require_owner(user_id)
    clean_title = clean_text(title, max_len=512)
    clean_description_zh = clean_text(description_zh, max_len=160)
    if not clean_title:
        raise InvalidPersonalProjectRequest("工具名称不能为空")
    if not clean_description_zh:
        raise InvalidPersonalProjectRequest("中文说明不能为空")

    clean_category = clean_text(category_slug, max_len=64)
    if clean_category not in WEBSITE_CATEGORY_BY_SLUG:
        clean_category = "other"
    clean_subcategory, subcategory_name = normalize_subcategory(
        clean_category,
        subcategory_slug,
        subcategory_by_category_slug=WEBSITE_SUBCATEGORY_BY_CATEGORY_SLUG,
        default_subcategory_by_category=WEBSITE_DEFAULT_SUBCATEGORY_BY_CATEGORY,
    )
    clean_tags: list[str] = []
    for tag in tags or []:
        clean_tag = clean_text(tag, max_len=24)
        if clean_tag and clean_tag not in clean_tags:
            clean_tags.append(clean_tag)
        if len(clean_tags) >= 4:
            break
    return {
        "user_id": owner_id,
        "website_id": int(website_id),
        "title": clean_title,
        "description": clean_text(description, max_len=2000),
        "image_url": clean_text(image_url, max_len=1024),
        "description_zh": clean_description_zh,
        "description_en": clean_text(description_en, max_len=512),
        "category_slug": clean_category,
        "category_name": WEBSITE_CATEGORY_BY_SLUG[clean_category],
        "category_name_zh": WEBSITE_CATEGORY_BY_SLUG[clean_category],
        "category_name_en": ENGLISH_LABEL_BY_SLUG[clean_category],
        "subcategory_slug": clean_subcategory,
        "subcategory_name": subcategory_name,
        "subcategory_name_zh": subcategory_name,
        "subcategory_name_en": ENGLISH_LABEL_BY_SLUG[clean_subcategory],
        "tags": clean_tags,
    }


class PersonalProjectsService:
    """Coordinate one owner's favorites and private website collection."""

    def __init__(
        self,
        *,
        collection: UserProjectCollectionRepository,
        enrichment: ToolWebsiteEnrichmentRepository,
        enricher_factory: WebsiteEnricherFactory = _default_enricher_factory,
        run_sync: ThreadRunner = asyncio.to_thread,
    ) -> None:
        self._collection = collection
        self._enrichment = enrichment
        self._enricher_factory = enricher_factory
        self._run_sync = run_sync

    async def list_collection(
        self, *, user_id: int, source: str = "all", **filters: Any
    ) -> dict[str, Any]:
        owner_id = _require_owner(user_id)
        return await self._run_sync(
            self._collection.list_user_project_collection,
            user_id=owner_id,
            source=_normalize_source(source),
            **filters,
        )

    async def get_categories(
        self, *, user_id: int, source: str = "all", **filters: Any
    ) -> dict[str, Any]:
        owner_id = _require_owner(user_id)
        return await self._run_sync(
            self._collection.get_user_project_categories,
            user_id=owner_id,
            source=_normalize_source(source),
            **filters,
        )

    async def get_tags(
        self, *, user_id: int, source: str = "github", **filters: Any
    ) -> dict[str, Any]:
        owner_id = _require_owner(user_id)
        return await self._run_sync(
            self._collection.get_user_project_tags,
            user_id=owner_id,
            source=_normalize_source(source),
            **filters,
        )

    async def add_favorite(
        self,
        *,
        user_id: int,
        source: str,
        repo_id: Any = None,
        website_id: Any = None,
    ) -> dict[str, Any]:
        owner_id = _require_owner(user_id)
        try:
            return await self._run_sync(
                self._collection.add_project_favorite,
                user_id=owner_id,
                source=source,
                repo_id=repo_id,
                website_id=website_id,
            )
        except ValueError as exc:
            raise InvalidPersonalProjectRequest(str(exc)) from exc
        except LookupError as exc:
            raise PersonalProjectNotFound(str(exc)) from exc

    async def remove_favorite(
        self,
        *,
        user_id: int,
        source: str,
        repo_id: Any = None,
        website_id: Any = None,
    ) -> bool:
        owner_id = _require_owner(user_id)
        try:
            return await self._run_sync(
                self._collection.remove_project_favorite,
                user_id=owner_id,
                source=source,
                repo_id=repo_id,
                website_id=website_id,
            )
        except ValueError as exc:
            raise InvalidPersonalProjectRequest(str(exc)) from exc
        except LookupError as exc:
            raise PersonalProjectNotFound(str(exc)) from exc

    async def add_tool_website(self, *, user_id: int, url: str) -> dict[str, Any]:
        owner_id = _require_owner(user_id)
        clean_url = (url or "").strip()
        if not clean_url:
            raise InvalidPersonalProjectRequest("URL 不能为空")
        try:
            enricher = self._enricher_factory(self._enrichment)
            result = await self._run_sync(
                enricher.add_and_enrich,
                clean_url,
                added_by_user_id=owner_id,
                visibility="private",
            )
            if result.get("blocked"):
                raise WebsiteContentBlockedError(
                    "检测到成人或不适宜内容，无法收藏该网址"
                )
            item = await self._link_enriched_website(
                owner_id=owner_id,
                result=result,
                added_via="existing" if result.get("duplicate") else "auto",
            )
        except ToolWebsiteFetchError as exc:
            raise InvalidPersonalProjectRequest(str(exc)) from exc
        except ModerationUnavailableError as exc:
            raise PersonalWebsiteOperationFailed(str(exc)) from exc
        except PersonalProjectsError:
            raise
        except (ValueError, LookupError) as exc:
            raise InvalidPersonalProjectRequest(str(exc)) from exc
        except Exception as exc:
            raise PersonalWebsiteOperationFailed(
                f"工具网站添加或富化失败：{exc}"
            ) from exc

        duplicate = bool(result.get("duplicate"))
        enrichment_failed = bool(result.get("enrichment_failed"))
        if duplicate:
            message = "工具网站已存在，已加入我的收藏。"
        elif enrichment_failed:
            message = "工具网站已添加到我的收藏，AI 分类服务暂时不可用，可稍后编辑分类。"
        else:
            message = "工具网站已添加到我的收藏。"
        return {
            "status": "succeeded",
            "message": message,
            "duplicate": duplicate,
            "item": item,
        }

    async def add_tool_website_manual(
        self,
        *,
        user_id: int,
        url: str,
        title: str,
        description_zh: str,
        category_slug: str,
        subcategory_slug: str,
        tags: list[str],
        description_en: str = "",
    ) -> dict[str, Any]:
        owner_id = _require_owner(user_id)
        clean_url = (url or "").strip()
        clean_title = (title or "").strip()
        clean_description_zh = (description_zh or "").strip()
        if not clean_url:
            raise InvalidPersonalProjectRequest("URL 不能为空")
        if not clean_title:
            raise InvalidPersonalProjectRequest("工具名称不能为空")
        if not clean_description_zh:
            raise InvalidPersonalProjectRequest("中文说明不能为空")
        try:
            enricher = self._enricher_factory(self._enrichment)
            result = await self._run_sync(
                enricher.add_manual,
                url=clean_url,
                title=clean_title,
                description_zh=clean_description_zh,
                category_slug=category_slug,
                subcategory_slug=subcategory_slug,
                tags=tags,
                added_by_user_id=owner_id,
                visibility="private",
            )
            if result.get("blocked"):
                raise WebsiteContentBlockedError(
                    "检测到成人或不适宜内容，无法收藏该网址"
                )
            item = result.get("item") or {}
            website_id = item.get("website_id")
            if website_id:
                link_state = await self._run_sync(
                    self._collection.link_user_tool_website,
                    user_id=owner_id,
                    website_id=int(website_id),
                    added_via="manual",
                )
                payload = build_tool_website_override(
                    user_id=owner_id,
                    website_id=int(website_id),
                    title=clean_title,
                    description_zh=clean_description_zh,
                    description_en=description_en,
                    category_slug=category_slug,
                    subcategory_slug=subcategory_slug,
                    tags=tags,
                    description=clean_description_zh,
                )
                item = await self._run_sync(
                    self._collection.upsert_user_tool_website_override,
                    payload,
                )
                if item:
                    item.update(link_state)
        except ToolWebsiteFetchError as exc:
            raise InvalidPersonalProjectRequest(str(exc)) from exc
        except ModerationUnavailableError as exc:
            raise PersonalWebsiteOperationFailed(str(exc)) from exc
        except PersonalProjectsError:
            raise
        except (ValueError, LookupError) as exc:
            raise InvalidPersonalProjectRequest(str(exc)) from exc
        except Exception as exc:
            raise PersonalWebsiteOperationFailed(
                f"工具网站手动添加失败：{exc}"
            ) from exc

        duplicate = bool(result.get("duplicate"))
        return {
            "status": "succeeded",
            "message": "工具网站已存在，已加入我的收藏。" if duplicate else "工具网站已手动添加到我的收藏。",
            "duplicate": duplicate,
            "item": item,
        }

    async def update_tool_website(
        self,
        *,
        user_id: int,
        website_id: int,
        title: str,
        description: str,
        description_zh: str,
        category_slug: str,
        subcategory_slug: str,
        tags: list[str],
        image_url: str,
        description_en: str = "",
    ) -> dict[str, Any]:
        payload = build_tool_website_override(
            user_id=user_id,
            website_id=website_id,
            title=title,
            description=description,
            description_zh=description_zh,
            description_en=description_en,
            category_slug=category_slug,
            subcategory_slug=subcategory_slug,
            tags=tags,
            image_url=image_url,
        )
        try:
            return await self._run_sync(
                self._collection.upsert_user_tool_website_override,
                payload,
            )
        except ValueError as exc:
            raise InvalidPersonalProjectRequest(str(exc)) from exc
        except LookupError as exc:
            raise PersonalProjectNotFound(str(exc)) from exc

    async def remove_tool_website(self, *, user_id: int, website_id: int) -> bool:
        owner_id = _require_owner(user_id)
        return await self._run_sync(
            self._collection.unlink_user_tool_website,
            user_id=owner_id,
            website_id=website_id,
        )

    async def _link_enriched_website(
        self,
        *,
        owner_id: int,
        result: dict[str, Any],
        added_via: str,
    ) -> dict[str, Any]:
        item = result.get("item") or {}
        website_id = item.get("website_id")
        if not website_id:
            return item
        link_state = await self._run_sync(
            self._collection.link_user_tool_website,
            user_id=owner_id,
            website_id=int(website_id),
            added_via=added_via,
        )
        owner_item = await self._run_sync(
            self._collection.get_tool_website_item_for_user,
            user_id=owner_id,
            website_id=int(website_id),
        )
        if owner_item:
            owner_item.update(link_state)
            return owner_item
        return owner_item
