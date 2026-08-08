from __future__ import annotations

"""Administrative batch briefing generation commands."""

import logging
from typing import Any, AsyncIterator, Protocol

logger = logging.getLogger(__name__)

# 简报仅按日生成；与 dispatch.BRIEFING_SOURCES 保持同一维度清单。
BRIEFING_SOURCES = (
    "all",
    "arxiv",
    "github",
    "news",
    "producthunt",
    "hackernews",
    "x",
    "dailyhot",
)


class BriefingGenerator(Protocol):
    def stream_generate(
        self,
        target_date: str | None = None,
        source: str = "all",
        force_regenerate: bool = True,
        locale: str = "zh-CN",
        generate_bilingual: bool = False,
    ) -> AsyncIterator[dict[str, Any]]: ...


class BriefingAdminService:
    """Generate every daily briefing dimension with per-dimension isolation."""

    def __init__(self, briefing: BriefingGenerator) -> None:
        self._briefing = briefing

    async def generate_all(self, force_regenerate: bool) -> None:
        success = 0
        for source in BRIEFING_SOURCES:
            try:
                async for _ in self._briefing.stream_generate(
                    target_date=None,
                    source=source,
                    force_regenerate=force_regenerate,
                ):
                    pass
                success += 1
                logger.info(
                    "[Ops] 简报生成完成: source=%s", source
                )
            except Exception as exc:
                logger.error(
                    "[Ops] 简报生成失败: source=%s error=%s",
                    source,
                    exc,
                    exc_info=True,
                )
        logger.info(
            "[Ops] 全维度简报生成完毕，%d/%d 成功。",
            success,
            len(BRIEFING_SOURCES),
        )
