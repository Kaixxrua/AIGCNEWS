from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Callable, Mapping, Protocol, Sequence

from backend.app.services.briefing.x_window import (
    X_ANCHOR_HOUR,
    x_briefing_cache_date,
    x_rolling_window_bounds,
)
from backend.app.services.dashboard.policy import (
    DEFAULT_SOURCE_DAY_BOUNDARY,
    FINALIZE_HOUR,
    SOURCE_DAY_BOUNDARY,
    SOURCE_FINALIZE_HOUR,
)

Document = dict[str, Any]
PromptConfig = Mapping[str, tuple[str, str]]
CountItems = Callable[[list[Document], str], int]
# (source, board_date, limit) -> 该源该日已定稿日榜的条目
ReadBoard = Callable[[str, str, int], list[Document]]


def _default_count_items(documents: list[Document], _source: str) -> int:
    return len(documents)

# ── 已定稿榜单口径 ──────────────────────────────────────────────────────
#
# 简报期号 P（target_date）的发布锚点是 P 日 08:00 CST，与 X 固定窗口同一
# 锚点。各源 D 日榜在 D+1 日 finalize_hour（CST）定稿（dashboard.policy 分源
# 契约），简报取锚点前已定稿的最近一张榜：finalize_hour <= 锚点 → D = P-1
# （北京日界源 01:00 关榜）；否则 D = P-2（太平洋日界源 17:00 才定稿，8 点时
# 昨日榜仍在收票）。规则只看期号不看墙钟：同一期何时重生成都读同一组榜。
# dailyhot 不在看板分源契约内：北京日界、每小时采集、23:07 末次落快照。
_BOARD_FINALIZE_HOUR: dict[str, int] = {**SOURCE_FINALIZE_HOUR, "dailyhot": 1}
_BOARD_DAY_BOUNDARY: dict[str, str] = {**SOURCE_DAY_BOUNDARY, "dailyhot": "CST"}

# 综合简报榜单日期说明里的源名（提示词内文案，英文稿由模型按语言指令翻译）
_BOARD_LABELS: dict[str, str] = {
    "arxiv": "论文",
    "github": "GitHub",
    "news": "新闻",
    "producthunt": "Product Hunt",
    "hackernews": "Hacker News",
    "dailyhot": "中文站点",
}


def finalized_board_date(publish_date: str, source: str) -> str:
    """期号 publish_date 的简报读取 source 的哪一日榜（见上方口径说明）。

    publish_date 非法时原样返回：按该串读榜必然为空，走无数据分支，不阻断。
    """
    try:
        publish = date.fromisoformat(publish_date)
    except ValueError:
        return publish_date
    finalize_hour = _BOARD_FINALIZE_HOUR.get(source, FINALIZE_HOUR)
    lag_days = 1 if finalize_hour <= X_ANCHOR_HOUR else 2
    return (publish - timedelta(days=lag_days)).isoformat()


class RollingDocumentReader(Protocol):
    def list_recent_by_source(
        self,
        source: str,
        *,
        since_iso: str,
        until_iso: str | None = None,
        limit: int = 500,
    ) -> list[Document]: ...


@dataclass(frozen=True)
class BoardSlice:
    """简报读取的一张已定稿日榜。"""

    source: str
    board_date: str
    day_boundary: str


@dataclass(frozen=True)
class BriefingContext:
    target_date: str
    source: str
    cache_date: str
    boards: tuple[BoardSlice, ...]
    rolling_sources: tuple[str, ...]


@dataclass(frozen=True)
class PreparedBriefing:
    context: BriefingContext
    documents: tuple[Document, ...]
    prompt: str | None
    milvus_used: bool = False


def normalize_briefing_context(
    *,
    target_date: str,
    source: str,
    source_config: PromptConfig,
    board_sources: Sequence[str],
) -> BriefingContext:
    normalized_source = source if source in source_config else "all"
    _, cache_suffix = source_config[normalized_source]

    if normalized_source == "all":
        board_names = tuple(board_sources)
        rolling_sources: tuple[str, ...] = ("x",)
    elif normalized_source == "x":
        board_names = ()
        rolling_sources = ("x",)
        cache_suffix = ""
    else:
        board_names = (
            (normalized_source,) if normalized_source in board_sources else ()
        )
        rolling_sources = ()

    cache_date = (
        x_briefing_cache_date(target_date)
        if normalized_source == "x"
        else f"{target_date}{cache_suffix}"
    )

    return BriefingContext(
        target_date=target_date,
        source=normalized_source,
        cache_date=cache_date,
        boards=tuple(
            BoardSlice(
                source=name,
                board_date=finalized_board_date(target_date, name),
                day_boundary=_BOARD_DAY_BOUNDARY.get(
                    name, DEFAULT_SOURCE_DAY_BOUNDARY
                ),
            )
            for name in board_names
        ),
        rolling_sources=rolling_sources,
    )


def _board_date_text(board_date: str, day_boundary: str) -> str:
    return f"{board_date}（太平洋时间）" if day_boundary == "PT" else board_date


def describe_board_dates(context: BriefingContext) -> str:
    """本期数据范围说明：单源只给榜日；综合按榜日分组列源，并附 X 窗口。"""
    if len(context.boards) == 1 and not context.rolling_sources:
        board = context.boards[0]
        return _board_date_text(board.board_date, board.day_boundary)
    groups: dict[tuple[str, str], list[str]] = {}
    for board in context.boards:
        groups.setdefault((board.board_date, board.day_boundary), []).append(
            _BOARD_LABELS.get(board.source, board.source)
        )
    parts = [
        f"{_board_date_text(board_date, boundary)}：{'、'.join(names)}"
        for (board_date, boundary), names in groups.items()
    ]
    if "x" in context.rolling_sources:
        start, end = x_rolling_window_bounds(context.target_date)
        parts.append(
            f"X：{start:%Y-%m-%d %H:%M} 至 {end:%Y-%m-%d %H:%M}（北京时间）"
        )
    return "；".join(parts)


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
        board_date=describe_board_dates(context),
    )


def _load_rolling_documents(
    context: BriefingContext,
    document_feed: RollingDocumentReader,
    top_k: int,
) -> list[Document]:
    """Load rolling-window documents for configured rolling sources."""
    if "x" not in context.rolling_sources:
        return []
    start, end = x_rolling_window_bounds(context.target_date)
    docs = document_feed.list_recent_by_source(
        source="x",
        since_iso=start.isoformat(),
        until_iso=end.isoformat(),
        limit=top_k * 3,
    )
    return list(docs)


def prepare_briefing(
    *,
    context: BriefingContext,
    top_k: int,
    read_board: ReadBoard,
    document_feed: RollingDocumentReader,
    source_config: PromptConfig,
    format_articles: Callable[[list[Document], str], str],
    is_blocked: Callable[[str], bool],
    count_items: CountItems = _default_count_items,
) -> PreparedBriefing:
    rolling_docs = _load_rolling_documents(context, document_feed, top_k)

    if context.source == "x":
        documents = _sort_documents_for_source(rolling_docs, source="x")[:top_k]
    else:
        # 只读已定稿日榜；某源榜缺失即该源缺席（诚实回空），不再用文档表
        # 近期入库条目兜底——兜底条目与任何一张榜都对不上。
        board_docs: list[Document] = []
        for board in context.boards:
            board_docs.extend(read_board(board.source, board.board_date, top_k))
        if context.source == "all":
            # 榜单全缺时不让 X 滚动窗口单独撑起一份"综合"简报
            documents = (
                interleave_documents_by_source(board_docs + rolling_docs, top_k=top_k)
                if board_docs
                else []
            )
        else:
            documents = order_snapshot_documents(
                board_docs,
                source=context.source,
                top_k=top_k,
            )

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
        milvus_used=False,
    )
