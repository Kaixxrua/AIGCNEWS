from __future__ import annotations

"""每日全维度简报生成与订阅邮件派发编排。

调度器（core.scheduler）仅注册本模块的回调句柄；简报流协议解析
（start/content/done/error）、正文拼接与逐订阅者邮件派发均归属 services 层。
"""

import logging
from typing import Any, Dict, List

from backend.app.repositories.application_repository_factory import (
    ApplicationRepositories,
)
from backend.app.repositories.briefing_repository import (
    BriefingDispatchSubscriptionRepository,
)
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


def _already_delivered(subscriber: Dict[str, Any], briefing_id: int) -> bool:
    last = subscriber.get("last_delivered_briefing_id")
    return last is not None and int(last) >= briefing_id


async def send_briefing_to_subscribers(
    *,
    source: str,
    date_str: str,
    content: str,
    briefing_id: int,
    subscriptions: BriefingDispatchSubscriptionRepository,
) -> int:
    subscribers = [
        subscriber
        for subscriber in subscriptions.get_active_subscribers(source=source)
        if not _already_delivered(subscriber, briefing_id)
    ]
    if not subscribers:
        return 0

    email_svc = email_service.build_email_service(None)

    sent = 0
    delivered_ids: list[int] = []
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
            subscriber_id = subscriber.get("id")
            if subscriber_id is not None:
                delivered_ids.append(int(subscriber_id))
        except Exception as exc:
            logger.error(
                "[Briefing] 订阅简报发送失败: source=%s email=%s error=%s",
                source,
                email,
                exc,
                exc_info=True,
            )
    if delivered_ids:
        try:
            subscriptions.mark_briefing_delivered(delivered_ids, briefing_id)
        except Exception as exc:
            # 标记失败最坏情况是下一次派发重复投递，不能因此让整轮任务失败。
            logger.error(
                "[Briefing] 投递标记回写失败: source=%s briefing_id=%s error=%s",
                source,
                briefing_id,
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
            stream_error = ""
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
                elif payload_type == "error":
                    stream_error = str(payload.get("data") or "unknown error")
            if stream_error:
                # 流内 error 载荷同样代表本维度失败，不计入成功数也不派发。
                logger.error(
                    "[Briefing] 简报生成失败: source=%s error=%s",
                    source,
                    stream_error,
                )
                continue
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
                    briefing_id=briefing_id,
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
