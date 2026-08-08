from __future__ import annotations

"""每日全维度简报生成与订阅邮件派发编排。

调度器（core.scheduler）仅注册本模块的回调句柄；简报流协议解析
（start/content/done）、正文拼接与逐订阅者邮件派发均归属 services 层。
"""

import logging
from typing import List

from backend.app.repositories.application_repository_factory import (
    ApplicationRepositories,
)
from backend.app.repositories.briefing_repository import ActiveBriefingSubscriberReader
from backend.app.services import email_service
from backend.app.services.briefing.composition import provide_daily_briefing_service

logger = logging.getLogger(__name__)

BRIEFING_SOURCES: List[str] = [
    "all",
    "arxiv",
    "github",
    "news",
    "producthunt",
    "hackernews",
    "x",
    "dailyhot",
]


async def send_briefing_to_subscribers(
    *,
    source: str,
    date_str: str,
    content: str,
    subscriptions: ActiveBriefingSubscriberReader,
) -> int:
    subscribers = subscriptions.get_active_subscribers(source=source)
    if not subscribers:
        return 0

    email_svc = email_service.build_email_service(None)

    sent = 0
    for subscriber in subscribers:
        email = subscriber.get("email")
        if not email:
            continue
        try:
            await email_svc.send_briefing(
                to_email=email,
                briefing_content=content,
                source=source,
                period="daily",
                date_str=date_str,
            )
            sent += 1
        except Exception as exc:
            logger.error(
                "[Briefing] 订阅简报发送失败: source=%s email=%s error=%s",
                source,
                email,
                exc,
                exc_info=True,
            )
    return sent


async def run_daily_briefing_dispatch(
    repositories: ApplicationRepositories,
) -> None:
    logger.info(
        "[Briefing] 触发每日自动简报生成（%d 个维度）...", len(BRIEFING_SOURCES)
    )
    service = provide_daily_briefing_service(repositories=repositories)
    success = 0
    for source in BRIEFING_SOURCES:
        try:
            content_parts: list[str] = []
            report_date = ""
            briefing_id = -1
            async for payload in service.stream_generate(
                target_date=None,
                source=source,
                force_regenerate=False,
                generate_bilingual=True,
            ):
                payload_type = payload.get("type")
                if payload_type == "start":
                    data = payload.get("data") or {}
                    report_date = str(data.get("date") or "")
                elif payload_type == "content":
                    content_parts.append(str(payload.get("data") or ""))
                elif payload_type == "done":
                    data = payload.get("data") or {}
                    briefing_id = int(data.get("briefing_id") or -1)
            success += 1
            logger.info(
                "[Briefing] 日报生成完成，准备推送订阅用户: source=%s",
                source,
            )
            content = "".join(content_parts)
            if briefing_id > 0 and content.strip() and report_date:
                sent = await send_briefing_to_subscribers(
                    source=source,
                    date_str=report_date,
                    content=content,
                    subscriptions=repositories.briefing_subscriptions,
                )
                logger.info(
                    "[Briefing] 订阅简报发送完成: source=%s sent=%d",
                    source,
                    sent,
                )
        except Exception as exc:
            logger.error(
                "[Briefing] 简报生成失败: source=%s error=%s",
                source,
                exc,
                exc_info=True,
            )

    logger.info(
        "[Briefing] 每日简报生成完毕，%d/%d 成功。", success, len(BRIEFING_SOURCES)
    )
