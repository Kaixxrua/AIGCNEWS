"""提前准备默认「今日热门」首页的速览，不让第一位访问者负责填缓存。"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from backend.app.services.project_catalog.peek_service import ProjectPeekService
from backend.app.services.project_catalog.query_service import ProjectCatalogQueryService

logger = logging.getLogger(__name__)
WARMUP_INTERVAL = 600
WARMUP_LIMIT = 24
_LOCK_KEY = "projects:peek:v1:warmup"


async def warm_project_peeks(
    redis: Any, peeks: ProjectPeekService, catalog: ProjectCatalogQueryService,
) -> None:
    # 多个 API worker 只选一个预热；锁自行过期，重启不会遗留永久锁。
    if not await redis.set(_LOCK_KEY, b"1", nx=True, ex=WARMUP_INTERVAL):
        return
    page = await catalog.list_public_projects(
        scope="today", category="", subcategory="", q="", language="",
        page=1, page_size=WARMUP_LIMIT, sort="hot", user_id=None,
    )
    repo_ids = list(dict.fromkeys(
        str(item["repo_id"]) for item in page.result.get("items", []) if item.get("repo_id")
    ))[:WARMUP_LIMIT]
    semaphore = asyncio.Semaphore(2)

    async def warm(repo_id: str) -> None:
        async with semaphore:
            try:
                await peeks.warm(repo_id, redis=redis)
            except Exception as exc:  # noqa: BLE001 - 单项失败不阻断其余速览
                logger.warning("[ProjectPeek] 预热 %s 失败：%s", repo_id, type(exc).__name__)

    await asyncio.gather(*(warm(repo_id) for repo_id in repo_ids))


async def maintain_project_peek_cache(redis: Any, peeks: ProjectPeekService) -> None:
    """启动立即预热；每十分钟接住榜单新项目，GitHub 现读仍受已有缓存和额度保护。"""
    catalog = ProjectCatalogQueryService()
    while True:
        try:
            await asyncio.wait_for(warm_project_peeks(redis, peeks, catalog), timeout=180)
        except Exception as exc:  # noqa: BLE001 - 后台维护失败不能影响 API
            logger.warning("[ProjectPeek] 预热维护失败：%s", type(exc).__name__)
        await asyncio.sleep(WARMUP_INTERVAL)
