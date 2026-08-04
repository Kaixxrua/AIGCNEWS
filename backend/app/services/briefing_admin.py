from __future__ import annotations

"""Administrative batch briefing generation commands."""

import logging
from typing import Any, AsyncIterator, Protocol

logger = logging.getLogger(__name__)

BRIEFING_DIMENSIONS = (
    ("all", "daily"),
    ("arxiv", "daily"),
    ("github", "daily"),
    ("news", "daily"),
    ("producthunt", "daily"),
    ("hackernews", "daily"),
    ("x", "daily"),
)


class BriefingGenerator(Protocol):
    def stream_generate(
        self,
        target_date: str | None = None,
        source: str = "all",
        period: str = "daily",
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
        for source, period in BRIEFING_DIMENSIONS:
            try:
                async for _ in self._briefing.stream_generate(
                    target_date=None,
                    source=source,
                    period=period,
                    force_regenerate=force_regenerate,
                ):
                    pass
                success += 1
                logger.info(
                    "[Ops] 简报生成完成: source=%s period=%s", source, period
                )
            except Exception as exc:
                logger.error(
                    "[Ops] 简报生成失败: source=%s period=%s error=%s",
                    source,
                    period,
                    exc,
                    exc_info=True,
                )
        logger.info(
            "[Ops] 全维度简报生成完毕，%d/%d 成功。",
            success,
            len(BRIEFING_DIMENSIONS),
        )
