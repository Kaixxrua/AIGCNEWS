from __future__ import annotations

"""X 已删推文 janitor：探测存量 X 文档，清掉原作者已删的推文与引用卡。

删除口径（2026-08-13 用户拍板）：只认作者删除——传输层把墓碑文案、
TweetUnavailable reason=="Deleted"、GraphQL code 144 归为 deleted；
Suspended/protected/404/网络/解析漂移一律 fail-closed 不动。被引推文
被作者删除时把外层文档的 quote 置 NULL（引用卡整体消失，正文保留）。

fail-closed 总则：鉴权失效/限流/无凭据 → 整轮中止（aborted 报告）、
零写入；单条探测不清的一律记 unknown 不动。
"""

import asyncio
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Protocol

from backend.app.repositories.document_repository import (
    DocumentWriter,
    DocumentXJanitorReader,
    DocumentXJanitorWriter,
)
from backend.app.services.ingestion.cache_invalidation import (
    clear_dashboard_cache_safely,
)
from backend.app.services.source_plugins import load_x_transport_class
from backend.app.services.source_plugins.x_source import (
    XAuthAbort,
    XAuthNotConfigured,
    XRateLimitAbort,
)

logger = logging.getLogger(__name__)

DEFAULT_MAX_PROBES_PER_RUN = 150

_TWEET_STATUS_RE = re.compile(r"/status/(\d+)")


def extract_tweet_id(url: Any) -> str:
    """从推文 URL 解析 tweet id（https://x.com/<handle>/status/<id>）；非推文 URL 返回空串。"""
    match = _TWEET_STATUS_RE.search(str(url or ""))
    return match.group(1) if match else ""


def extract_quoted_tweet_id(quote: Any) -> str:
    """从 quote 卡片元数据解析被引 tweet id；无卡/坏数据返回空串。"""
    if not isinstance(quote, dict):
        return ""
    return extract_tweet_id(quote.get("url"))


class XJanitorCredentialProvider(Protocol):
    """list_enabled_x_credentials 窄口（与 x_credentials 仓储对齐）。"""

    def list_enabled_x_credentials(self) -> list[dict[str, Any]]: ...


class XJanitorDocumentStore(
    DocumentXJanitorReader,
    DocumentXJanitorWriter,
    DocumentWriter,
    Protocol,
):
    """janitor 依赖的文档仓储窄口：探测读取 + 删文档 + 清引用卡。"""


@dataclass
class XJanitorReport:
    """单轮 janitor 运行结果。aborted 非 None 时本轮零写入。"""

    probed: int = 0
    alive: int = 0
    deleted: int = 0
    unavailable: int = 0
    unknown: int = 0
    deleted_doc_ids: list[str] = field(default_factory=list)
    cleared_quote_doc_ids: list[str] = field(default_factory=list)
    aborted: str | None = None


class XDeletedTweetJanitor:
    """探测存量 X 文档对应推文的存活状态，删除作者已删条目、清作者已删引用卡。

    Args:
        documents: 文档仓储（list_x_documents_for_probe / delete_documents /
            clear_quotes_for_docs）。
        x_credentials: 凭据仓储（list_enabled_x_credentials，供传输层凭据链）。
        transport: 可注入的传输层实例（测试用）；缺省经 load_x_transport_class()
            加载插件实现并以凭据仓储构造。
        max_probes_per_run: 单轮探测数上限（own + 被引合并计数）。
        x_lock: 与 X 采集/测活共享的操作锁；仅在探测调用期间持有。
    """

    def __init__(
        self,
        documents: XJanitorDocumentStore,
        x_credentials: XJanitorCredentialProvider,
        *,
        transport: Any = None,
        max_probes_per_run: int = DEFAULT_MAX_PROBES_PER_RUN,
        x_lock: asyncio.Lock | None = None,
    ) -> None:
        self._documents = documents
        self._x_credentials = x_credentials
        self._transport = transport
        self._max_probes = max(1, int(max_probes_per_run))
        self._x_lock = x_lock

    async def run(self) -> XJanitorReport:
        rows = await asyncio.to_thread(
            self._documents.list_x_documents_for_probe, self._max_probes
        )
        probe_ids, quoted_outers, own_by_doc = self._collect_probe_ids(rows)
        if not probe_ids:
            logger.info("[XJanitor] 无 X 文档可探测，本轮跳过。")
            return XJanitorReport()

        transport, abort_reason = self._resolve_transport()
        if transport is None:
            logger.warning("[XJanitor] 传输层不可用（%s），本轮中止。", abort_reason)
            return XJanitorReport(aborted=abort_reason)

        probe = getattr(transport, "probe_tweet_existence", None)
        if not callable(probe):
            logger.warning("[XJanitor] 传输层缺 probe_tweet_existence（overlay 版本错位），本轮中止。")
            return XJanitorReport(aborted="transport_missing_probe")

        lock = self._x_lock or asyncio.Lock()
        try:
            async with lock:
                statuses = await asyncio.to_thread(probe, probe_ids)
        except XAuthNotConfigured:
            logger.warning("[XJanitor] 无启用 X 凭据，本轮中止、零写入。")
            return XJanitorReport(aborted="x_auth_not_configured")
        except XAuthAbort:
            logger.warning("[XJanitor] X 凭据失效，本轮中止、零写入。")
            return XJanitorReport(aborted="x_auth_expired")
        except XRateLimitAbort:
            logger.warning("[XJanitor] X 限流，本轮中止、零写入。")
            return XJanitorReport(aborted="x_rate_limited")

        report = XJanitorReport(probed=len(statuses))
        for status in statuses.values():
            if status == "alive":
                report.alive += 1
            elif status == "deleted":
                report.deleted += 1
            elif status == "unavailable":
                report.unavailable += 1
            else:
                report.unknown += 1

        delete_ids = [
            doc_id
            for doc_id, own_id in own_by_doc.items()
            if statuses.get(own_id) == "deleted"
        ]
        clear_ids = [
            outer_id
            for quoted_id, outer_ids in quoted_outers.items()
            if statuses.get(quoted_id) == "deleted"
            for outer_id in outer_ids
            if statuses.get(own_by_doc.get(outer_id, "")) != "deleted"
        ]

        if delete_ids:
            report.deleted_doc_ids = await asyncio.to_thread(
                self._documents.delete_documents, delete_ids
            )
        if clear_ids:
            report.cleared_quote_doc_ids = await asyncio.to_thread(
                self._documents.clear_quotes_for_docs, clear_ids
            )
        if report.deleted_doc_ids or report.cleared_quote_doc_ids:
            await clear_dashboard_cache_safely()

        logger.info(
            "[XJanitor] 本轮探测 %d 条（alive %d / deleted %d / unavailable %d / "
            "unknown %d）；删除文档 %d 条，清理引用卡 %d 张。",
            report.probed,
            report.alive,
            report.deleted,
            report.unavailable,
            report.unknown,
            len(report.deleted_doc_ids),
            len(report.cleared_quote_doc_ids),
        )
        return report

    def _collect_probe_ids(
        self, rows: Iterable[dict[str, Any]]
    ) -> tuple[list[str], dict[str, list[str]], dict[str, str]]:
        """逐行取 own id + 被引 id，扁平去重截断到 cap。

        返回 (probe_ids, quoted_id -> [外层 doc_ids], doc_id -> own_id)。
        own id 缺失（畸形 URL）的文档整行跳过；被引 id 按首次出现去重，
        多个外层共用同一被引只探一次、清卡时全清。
        """
        probe_ids: list[str] = []
        seen: set[str] = set()
        quoted_outers: dict[str, list[str]] = {}
        own_by_doc: dict[str, str] = {}

        def _push(tweet_id: str) -> bool:
            if tweet_id in seen:
                return True
            if len(probe_ids) >= self._max_probes:
                return False
            seen.add(tweet_id)
            probe_ids.append(tweet_id)
            return True

        for row in rows:
            doc_id = str(row.get("id") or "")
            own_id = extract_tweet_id(row.get("url"))
            if not doc_id or not own_id:
                continue
            if not _push(own_id):
                break
            own_by_doc[doc_id] = own_id
            quoted_id = extract_quoted_tweet_id(row.get("quote"))
            if quoted_id and _push(quoted_id):
                quoted_outers.setdefault(quoted_id, []).append(doc_id)
        return probe_ids, quoted_outers, own_by_doc

    def _resolve_transport(self) -> tuple[Any | None, str | None]:
        if self._transport is not None:
            return self._transport, None
        transport_class = load_x_transport_class()
        if transport_class is None:
            return None, "x_transport_unavailable"
        return (
            transport_class(
                credential_provider=self._x_credentials.list_enabled_x_credentials
            ),
            None,
        )
