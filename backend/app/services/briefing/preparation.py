from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

Document = dict[str, Any]
PromptConfig = Mapping[str, tuple[str, str]]
PeriodChannels = Mapping[str, Mapping[str, str]]


@dataclass(frozen=True)
class BriefingContext:
    target_date: str
    source: str
    period: str
    cache_date: str
    period_label: str
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
    period: str,
    source_config: PromptConfig,
    period_labels: Mapping[str, str],
    period_channels: PeriodChannels,
) -> BriefingContext:
    normalized_source = source if source in source_config else "all"
    normalized_period = period if period in ("daily", "weekly", "monthly") else "daily"
    _, cache_suffix = source_config[normalized_source]

    if normalized_source == "all":
        expected_channels = tuple(
            channel
            for channels in period_channels.values()
            if (channel := channels.get(normalized_period))
        )
    else:
        channel = period_channels.get(normalized_source, {}).get(normalized_period)
        expected_channels = (channel,) if channel else ()

    return BriefingContext(
        target_date=target_date,
        source=normalized_source,
        period=normalized_period,
        cache_date=f"{target_date}{cache_suffix}_{normalized_period}",
        period_label=period_labels.get(normalized_period, "今日"),
        source_type=None if normalized_source == "all" else normalized_source,
        expected_channels=expected_channels,
    )


def order_snapshot_documents(
    documents: Sequence[Document],
    *,
    source: str,
    top_k: int,
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
    return ordered[:top_k]


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
        period_label=context.period_label,
    )
