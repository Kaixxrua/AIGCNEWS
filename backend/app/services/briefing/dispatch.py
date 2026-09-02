from __future__ import annotations

"""每日全维度简报生成与订阅邮件派发编排。

调度器（core.scheduler）仅注册本模块的回调句柄；简报流协议解析
（start/content/done/error）、正文拼接与逐订阅者邮件派发均归属 services 层。
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Dict, List

from backend.app.core.operations import ApplicationOperationsRuntime
from backend.app.repositories.application_repository_factory import (
    ApplicationRepositories,
)
from backend.app.repositories.briefing_repository import (
    BriefingDispatchSubscriptionRepository,
)
from backend.app.services import email_service
from backend.app.services.briefing.composition import provide_daily_briefing_service
from backend.app.services.briefing.daily_briefing import BriefingSavedNotifier
from backend.app.services.ingestion.base_crawler import today_cst
from backend.app.services.push.dispatch_service import SubscriptionDispatchService

logger = logging.getLogger(__name__)

DEFAULT_SOURCE_CONCURRENCY = 3
# LLM 流式生成并发上限：_stream_llm_round 在一轮流式期间全程占锁，
# 钉 1 会把所有维度的生成串成一条线（source 并发只剩数据准备重叠）。
# 与 source 并发对齐为 3；若 sub2api 中转站承压再下调。
DEFAULT_LLM_CONCURRENCY = 3

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


@dataclass(frozen=True)
class _DailyBriefingSourceResult:
    source: str
    report_date: str = ""
    content: str = ""
    briefing_id: int = -1
    error: str = ""

    @property
    def successful(self) -> bool:
        return (
            not self.error
            and self.briefing_id > 0
            and bool(self.report_date)
            and bool(self.content.strip())
        )


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
    redis_client: Any | None = None,
) -> int:
    subscribers = [
        subscriber
        for subscriber in subscriptions.get_active_subscribers(source=source)
        if not _already_delivered(subscriber, briefing_id)
    ]
    if not subscribers:
        return 0

    # redis_client 接入邮件池配额计数与熔断；None 时护栏 fail-open、
    # 退化为纯 failover（EmailPoolQuotaStore 既有契约）。
    email_svc = email_service.build_email_service(redis_client)

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


async def dispatch_saved_briefing_issue(
    repositories: ApplicationRepositories,
    *,
    source: str,
    report_date: str,
    briefing_id: int,
    content_zh: str,
    redis_client: Any | None = None,
) -> None:
    """已保存期次的订阅邮件补发：旧 briefing_subscriptions + 新 user_subscriptions(email)。

    供简报手动生成（报告页 SSE / 运维 generate-all）保存成功后自动补发。
    两体系各自走既有幂等账本（A 用 watermark，B 用 delivery ledger），互不
    迁移也不跨表去重；任一体系异常仅记录日志，不阻断另一体系，更不影响
    已保存的简报内容。
    """
    content = content_zh if content_zh.strip() else ""
    if not content or briefing_id <= 0 or not report_date:
        return

    try:
        sent = await send_briefing_to_subscribers(
            source=source,
            date_str=report_date,
            content=content,
            briefing_id=briefing_id,
            subscriptions=repositories.briefing_subscriptions,
            redis_client=redis_client,
        )
        logger.info(
            "[Briefing] 手动生成后旧订阅补发完成: source=%s date=%s sent=%d",
            source,
            report_date,
            sent,
        )
    except Exception as exc:
        logger.error(
            "[Briefing] 手动生成后旧订阅补发失败: source=%s date=%s error=%s",
            source,
            report_date,
            exc,
            exc_info=True,
        )

    try:
        service = SubscriptionDispatchService(
            subscriptions=repositories.user_subscriptions,
            deliveries=repositories.push_deliveries,
            briefings=repositories.briefings,
            redis_client=redis_client,
        )
        summary = await service.dispatch_issue(
            source=source,
            report_date=report_date,
            content=content,
        )
        logger.info(
            "[Briefing] 手动生成后订阅补发完成: source=%s date=%s summary=%s",
            source,
            report_date,
            summary,
        )
    except Exception as exc:
        logger.error(
            "[Briefing] 手动生成后订阅补发失败: source=%s date=%s error=%s",
            source,
            report_date,
            exc,
            exc_info=True,
        )


def build_briefing_saved_notifier(
    repositories: ApplicationRepositories,
    *,
    operations: ApplicationOperationsRuntime,
    redis_client: Any | None = None,
) -> BriefingSavedNotifier:
    """构造保存后通知：把已保存期次的订阅补发提交到应用后台运行时。

    由 ApplicationOperationsRuntime 托管任务，SSE 客户端断连不会取消 SMTP
    补发；运行时已停止（submit 返回 False）时只记录日志，不抛异常。
    """

    def _notify(
        *,
        report_date: str,
        source: str,
        cache_key: str,
        briefing_id: int,
        content_zh: str,
    ) -> None:
        submitted = operations.submit(
            dispatch_saved_briefing_issue,
            repositories,
            source=source,
            report_date=report_date,
            briefing_id=briefing_id,
            content_zh=content_zh,
            redis_client=redis_client,
        )
        if not submitted:
            logger.warning(
                "[Briefing] 后台运行时已停止，订阅补发未入队: source=%s briefing_id=%s",
                source,
                briefing_id,
            )

    return _notify


async def _run_daily_briefing_source(
    service: Any,
    source: str,
    *,
    target_date: str,
    limiter: asyncio.Semaphore,
) -> _DailyBriefingSourceResult:
    async with limiter:
        content_parts: list[str] = []
        report_date = ""
        briefing_id = -1
        stream_error = ""
        try:
            async for payload in service.stream_generate(
                target_date=target_date,
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
                logger.error(
                    "[Briefing] 简报生成失败: source=%s error=%s",
                    source,
                    stream_error,
                )
                return _DailyBriefingSourceResult(source=source, error=stream_error)
            result = _DailyBriefingSourceResult(
                source=source,
                report_date=report_date,
                content="".join(content_parts),
                briefing_id=briefing_id,
            )
            if result.successful:
                logger.info(
                    "[Briefing] 日报生成完成，准备推送订阅用户: source=%s", source
                )
            return result
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error(
                "[Briefing] 简报生成失败: source=%s error=%s",
                source,
                exc,
                exc_info=True,
            )
            return _DailyBriefingSourceResult(source=source, error=str(exc))


async def run_daily_briefing_dispatch(
    repositories: ApplicationRepositories,
    *,
    redis_client: Any | None = None,
    source_concurrency: int = DEFAULT_SOURCE_CONCURRENCY,
    llm_concurrency: int = DEFAULT_LLM_CONCURRENCY,
) -> None:
    if source_concurrency < 1 or llm_concurrency < 1:
        raise ValueError("briefing concurrency must be at least 1")
    logger.info(
        "[Briefing] 触发每日自动简报生成（%d 个维度）...", len(BRIEFING_SOURCES)
    )
    target_date = today_cst()
    llm_limiter = asyncio.Semaphore(llm_concurrency)
    service = provide_daily_briefing_service(
        repositories=repositories,
        llm_limiter=llm_limiter,
    )
    source_limiter = asyncio.Semaphore(source_concurrency)
    tasks = [
        asyncio.create_task(
            _run_daily_briefing_source(
                service,
                source,
                target_date=target_date,
                limiter=source_limiter,
            ),
            name=f"briefing-source-{source}",
        )
        for source in BRIEFING_SOURCES
    ]
    try:
        results = await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise

    by_source = {result.source: result for result in results}
    success = sum(1 for source in BRIEFING_SOURCES if by_source[source].successful)
    for source in BRIEFING_SOURCES:
        result = by_source[source]
        if not result.successful:
            continue
        try:
            sent = await send_briefing_to_subscribers(
                source=source,
                date_str=result.report_date,
                content=result.content,
                briefing_id=result.briefing_id,
                subscriptions=repositories.briefing_subscriptions,
                redis_client=redis_client,
            )
            logger.info(
                "[Briefing] 订阅简报发送完成: source=%s sent=%d", source, sent
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error(
                "[Briefing] 订阅简报发送失败: source=%s error=%s",
                source,
                exc,
                exc_info=True,
            )

    logger.info(
        "[Briefing] 每日简报生成完毕，%d/%d 成功。", success, len(BRIEFING_SOURCES)
    )
