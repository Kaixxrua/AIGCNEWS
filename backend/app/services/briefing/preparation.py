from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping, Protocol, Sequence

Document = dict[str, Any]
PromptConfig = Mapping[str, tuple[str, str]]
SourceChannels = Mapping[str, str]


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
    def get_top_documents(
        self, *, limit: int, source_type: str | None
    ) -> list[Document]: ...

    def get_latest_documents(self, *, limit: int) -> list[Document]: ...


@dataclass(frozen=True)
class BriefingContext:
    target_date: str
    source: str
    cache_date: str
    source_type: str | None
    expected_channels: tuple[str, ...]


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
    else:
        channel = source_channels.get(normalized_source)
        expected_channels = (channel,) if channel else ()

    return BriefingContext(
        target_date=target_date,
        source=normalized_source,
        cache_date=f"{target_date}{cache_suffix}",
        source_type=None if normalized_source == "all" else normalized_source,
        expected_channels=expected_channels,
    )


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
) -> str:
    prompt_template, _ = source_config[context.source]
    docs = list(documents)
    return prompt_template.format(
        count=len(docs),
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
        top_documents = document_feed.get_top_documents(
            limit=top_k * 3,
            source_type=context.source_type,
        )
        filtered = filter_by_channel(
            top_documents,
            context.source,
        )
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
