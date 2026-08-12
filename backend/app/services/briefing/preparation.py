from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Callable, Mapping, Protocol, Sequence

Document = dict[str, Any]
PromptConfig = Mapping[str, tuple[str, str]]
SourceChannels = Mapping[str, str]
CountItems = Callable[[list[Document], str], int]


def _default_count_items(documents: list[Document], _source: str) -> int:
    return len(documents)

# 快照缺失时的文档表兜底窗口：目标日及前 1 天（按入库时间）。
# 日榜快照在次日 00:3x 关榜后才定稿，早间生成"今日"简报时今日快照尚未就绪，
# 兜底窗口必须约束在近期入库文档，否则全表按分数排序会把旧热点混进"今日"报。
_FALLBACK_RECENT_DAYS = 1


class SnapshotDocumentReader(Protocol):
    def get_snapshot_documents(
        self,
        *,
        snapshot_date: str,
        source_channel: str,
        source_type: str | None,
        limit: int,
    ) -> list[Document]: ...


class DocumentFallbackReader(Protocol):
    def get_recent_top_documents(
        self,
        *,
        source_type: str,
        since_date: str,
        limit: int,
    ) -> list[Document]: ...

    def get_latest_documents(self, *, limit: int) -> list[Document]: ...


@dataclass(frozen=True)
class BriefingContext:
    target_date: str
    source: str
    cache_date: str
    source_type: str | None
    expected_channels: tuple[str, ...]
    fallback_sources: tuple[str, ...]


@dataclass(frozen=True)
class PreparedBriefing:
    context: BriefingContext
    documents: tuple[Document, ...]
    prompt: str | None
    fallback_used: bool = False
    milvus_used: bool = False


def normalize_briefing_context(
    *,
    target_date: str,
    source: str,
    source_config: PromptConfig,
    source_channels: SourceChannels,
) -> BriefingContext:
    normalized_source = source if source in source_config else "all"
    _, cache_suffix = source_config[normalized_source]

    if normalized_source == "all":
        expected_channels = tuple(source_channels.values())
        fallback_sources = tuple(source_channels.keys())
    else:
        channel = source_channels.get(normalized_source)
        expected_channels = (channel,) if channel else ()
        fallback_sources = (normalized_source,) if channel else ()

    return BriefingContext(
        target_date=target_date,
        source=normalized_source,
        cache_date=f"{target_date}{cache_suffix}",
        source_type=None if normalized_source == "all" else normalized_source,
        expected_channels=expected_channels,
        fallback_sources=fallback_sources,
    )


def _recent_window_start(target_date: str) -> str:
    """兜底日期域起点（含）：目标日往前 _FALLBACK_RECENT_DAYS 天。

    target_date 非法时原样返回（词法比较退化为当日单天），不阻断生成。
    """
    try:
        end = date.fromisoformat(target_date)
    except ValueError:
        return target_date
    return (end - timedelta(days=_FALLBACK_RECENT_DAYS)).isoformat()


def _sort_documents_for_source(
    documents: Sequence[Document],
    source: str,
) -> list[Document]:
    ordered = list(documents)
    if source == "github":
        ordered.sort(
            key=lambda document: (
                int(document.get("rank_in_period") or 9999),
                -(float(document.get("raw_score") or document.get("score") or 0)),
            )
        )
    else:
        ordered.sort(
            key=lambda document: (
                document.get("raw_score") or document.get("score") or 0
            ),
            reverse=True,
        )
    return ordered


def order_snapshot_documents(
    documents: Sequence[Document],
    *,
    source: str,
    top_k: int,
) -> list[Document]:
    return _sort_documents_for_source(documents, source)[:top_k]


def interleave_documents_by_source(
    documents: Sequence[Document],
    *,
    top_k: int,
) -> list[Document]:
    """跨源轮询选取：按 doc["source"] 分桶、桶内按该源规则排序后逐桶轮取。

    各来源的 raw_score 量纲差异巨大（dailyhot 热度数千、news 仅 1-2 分），
    全局按分数排序截断会让低分来源整源缺席综合简报；轮询保证每个有数据
    的来源都能进入结果，直到凑满 top_k。
    """
    buckets: dict[str, list[Document]] = {}
    for document in documents:
        source = str(document.get("source") or "").lower()
        buckets.setdefault(source, []).append(document)
    ordered_buckets = [
        _sort_documents_for_source(bucket, source)
        for source, bucket in buckets.items()
    ]

    selected: list[Document] = []
    positions = [0] * len(ordered_buckets)
    while len(selected) < top_k:
        progressed = False
        for bucket_index, bucket in enumerate(ordered_buckets):
            if len(selected) >= top_k:
                break
            position = positions[bucket_index]
            if position < len(bucket):
                selected.append(bucket[position])
                positions[bucket_index] = position + 1
                progressed = True
        if not progressed:
            break
    return selected


def remove_blocked_documents(
    documents: Sequence[Document],
    *,
    is_blocked: Callable[[str], bool],
) -> list[Document]:
    return [
        document
        for document in documents
        if not is_blocked(
            "\n".join(
                str(document.get(key) or "") for key in ("title", "summary", "url")
            )
        )
    ]


def render_briefing_prompt(
    *,
    context: BriefingContext,
    documents: Sequence[Document],
    source_config: PromptConfig,
    format_articles: Callable[[list[Document], str], str],
    count_items: CountItems = _default_count_items,
) -> str:
    prompt_template, _ = source_config[context.source]
    docs = list(documents)
    return prompt_template.format(
        count=count_items(docs, context.source),
        articles=format_articles(docs, context.source),
        date=context.target_date,
    )


def prepare_briefing(
    *,
    context: BriefingContext,
    top_k: int,
    snapshot_reader: SnapshotDocumentReader,
    document_feed: DocumentFallbackReader,
    source_config: PromptConfig,
    filter_by_channel: Callable[[list[Document], str], list[Document]],
    format_articles: Callable[[list[Document], str], str],
    is_blocked: Callable[[str], bool],
    count_items: CountItems = _default_count_items,
) -> PreparedBriefing:
    documents: list[Document] = []
    fallback_used = False

    for channel in context.expected_channels:
        documents.extend(
            snapshot_reader.get_snapshot_documents(
                snapshot_date=context.target_date,
                source_channel=channel,
                source_type=context.source_type,
                limit=top_k,
            )
        )

    if documents:
        if context.source == "all":
            # 综合简报：跨源轮询，避免高分量纲来源挤掉其他来源。
            documents = interleave_documents_by_source(documents, top_k=top_k)
        else:
            documents = order_snapshot_documents(
                documents,
                source=context.source,
                top_k=top_k,
            )
    else:
        # 快照未就绪（早间生成时今日快照尚未关榜）→ 文档表日期域兜底：
        # 逐源在近期窗口内按分数取候选，再过滤 channel + 跨源轮询。
        # 旧实现全表按 raw_score 取 top_k*3，低分量纲源（news/arxiv 等）
        # 在截断处整源缺席，且无日期约束会混入陈旧条目。
        since_date = _recent_window_start(context.target_date)
        per_source_limit = top_k if context.source == "all" else top_k * 3
        recent: list[Document] = []
        for fallback_source in context.fallback_sources:
            recent.extend(
                document_feed.get_recent_top_documents(
                    source_type=fallback_source,
                    since_date=since_date,
                    limit=per_source_limit,
                )
            )
        filtered = filter_by_channel(recent, context.source)
        if context.source == "all":
            documents = interleave_documents_by_source(filtered, top_k=top_k)
        else:
            documents = filtered[:top_k]

    if not documents:
        documents = document_feed.get_latest_documents(limit=top_k)
        fallback_used = True

    documents = remove_blocked_documents(documents, is_blocked=is_blocked)
    prompt = (
        render_briefing_prompt(
            context=context,
            documents=documents,
            source_config=source_config,
            format_articles=format_articles,
            count_items=count_items,
        )
        if documents
        else None
    )
    return PreparedBriefing(
        context=context,
        documents=tuple(documents),
        prompt=prompt,
        fallback_used=fallback_used,
        milvus_used=False,
    )
