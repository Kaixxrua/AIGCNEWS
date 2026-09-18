from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from typing import Any, Sequence, TypedDict

from starlette.requests import Request

RADAR_CATEGORIES = {
    "大模型": [
        "llm",
        "foundation model",
        "language model",
        "gpt",
        "llama",
        "qwen",
        "mistral",
        "gemma",
        "deepseek",
        "moe",
        "transformer",
        "reasoning",
    ],
    "智能体": [
        "agent",
        "agents",
        "multi-agent",
        "autonomous",
        "tool use",
        "function calling",
        "planning",
        "workflow",
        "orchestration",
    ],
    "多模态": [
        "multimodal",
        "vision-language",
        "vlm",
        "image",
        "video",
        "audio",
        "speech",
        "ocr",
    ],
    "数据与评测": [
        "dataset",
        "data curation",
        "synthetic data",
        "benchmark",
        "evaluation",
        "eval",
        "leaderboard",
        "alignment",
        "safety",
    ],
    "系统与部署": [
        "inference",
        "serving",
        "deployment",
        "quantization",
        "distillation",
        "onnx",
        "vllm",
        "triton",
        "latency",
        "throughput",
        "edge",
    ],
}

SOURCE_WEIGHTS: dict[str, float] = {
    "arxiv": 1.0,
    "github": 1.0,
    "news": 1.0,
    "producthunt": 1.0,
    "hackernews": 1.0,
    "x": 1.0,
}

FINALIZE_HOUR = 15

# ── 分源定稿契约 ────────────────────────────────────────────────────────
#
# 每个源的自然日界：决定"这个源的一天何时真正结束"。定稿必须等到源日界
# 结束后的末次采集完成，而不是统一的整榜时钟标签（compute_board_status
# 的 FINALIZE_HOUR 一刀切语义保持不动，作为整榜可见性闸门继续服役）。
SOURCE_DAY_BOUNDARY: dict[str, str] = {
    "arxiv": "PT",  # HF Daily Papers 页面日期（美国日界）
    "github": "CST",  # v5 热度指标（自有数据，CST 日界）
    "news": "CST",  # Techmeme RSS 滚动窗，CST 归属
    "producthunt": "PT",  # featuredAt 的太平洋日期
    "hackernews": "CST",  # 滚动 24h 窗，CST 归属
    "x": "CST",  # 推文发布时间（CST 日界）
}

# 分源关榜时刻（次日 CST 整点）：源日界结束 + 末次采集窗口后的揭榜时刻。
# PT 源取 17：PST 冬令时 PT 0:00 = CST 16:00，留 1h 末次采集窗口；PDT
# 夏令时 = CST 15:00，窗口 2h。CST 源取 1：00:3x 关榜采集收完当天尾巴。
SOURCE_FINALIZE_HOUR: dict[str, int] = {
    "arxiv": 17,
    "github": 1,
    "news": 1,
    "producthunt": 17,
    "hackernews": 1,
    "x": 1,
}

# 未知/未注册源的保守口径：PT 日界 + 旧版整榜时刻，行为与历史一致。
DEFAULT_SOURCE_DAY_BOUNDARY = "PT"


class SourceBoardStatus(TypedDict):
    """单源榜单状态：整榜 is_finalized/is_embargoed 之外的分源契约。

    finalize_hour 为该源揭榜时刻（次日 CST 整点），供前端提示
    "预计 HH:00 定稿"；day_boundary 标明该源的自然日界口径。
    is_disabled 标明可插拔源被特性开关关闭（wire 只增字段，旧消费端忽略）。
    """

    is_finalized: bool
    is_embargoed: bool
    day_boundary: str
    finalize_hour: int
    is_disabled: bool

# 看板 github 榜自 v5 热度指标表读取后，条目的来源渠道标记。
# 与 rank_snapshots 的 github_trending_daily/github_hot_daily 区分开，
# 便于排查口径（response items[].source_channel 可见）。
GITHUB_METRICS_DAILY_CHANNEL = "github_metrics_daily"


def github_metric_to_doc(row: dict[str, Any], rank: int) -> dict[str, Any]:
    """把项目库日度热度指标行映射为看板 doc 形状（与 rank_snapshots 文档同构）。

    前端看板按 doc 形状渲染（title/url/stars/language/summary + raw_score
    兜底），此处保持 wire 兼容；日增、基线日期、热度分作为附加字段透出，
    旧前端忽略、新前端可用。rank 为按 hot_score 排序后的 1 起始名次。
    """
    topics_raw = row.get("topics_json") or ""
    topics: list[str] = []
    if topics_raw:
        try:
            parsed = json.loads(topics_raw)
        except (TypeError, ValueError):
            parsed = None
        if isinstance(parsed, list):
            topics = [str(item) for item in parsed if item]
    metric_date = str(row.get("metric_date") or "")
    daily_growth = int(row.get("daily_star_growth") or 0)
    hot_score = float(row.get("hot_score") or 0.0)
    return {
        "id": row.get("repo_id"),
        "source": "github",
        "title": row.get("full_name"),
        "url": row.get("url"),
        "summary": row.get("description") or "",
        "stars": int(row.get("stars") or 0),
        "forks": int(row.get("forks") or 0),
        "language": row.get("language") or "",
        "tags": topics,
        # raw_score/score 沿用看板既有语义：github 的展示主字段是 stars，
        # raw_score 兜底取日增（doc_weight 也读它），score 承载 hot_score。
        "raw_score": float(daily_growth),
        "score": hot_score,
        "image_url": row.get("image_url"),
        "daily_growth_available": True,
        "rank_in_period": rank,
        "source_channel": GITHUB_METRICS_DAILY_CHANNEL,
        "snapshot_date": metric_date,
        "published_date": metric_date,
        "published_at": None,
        "daily_star_growth": daily_growth,
        "daily_growth_source": row.get("daily_growth_source"),
        "previous_snapshot_date": row.get("previous_snapshot_date"),
        "hot_score": hot_score,
        # 反作弊一二层打标（仅透出，不参与排序）
        "growth_suspicion_score": float(row.get("growth_suspicion_score") or 0.0),
        "growth_suspicion_signals": row.get("growth_suspicion_signals") or "[]",
        "growth_corroborated": bool(row.get("growth_corroborated")),
    }


def enrich_doc_pdf_url(doc: dict[str, Any], request: Request) -> dict[str, Any]:
    """Keep legacy clients compatible without advertising retired PDF endpoints."""
    doc["pdf_media_url"] = None
    return doc


def doc_weight(doc: dict[str, Any]) -> float:
    source = (doc.get("source") or "arxiv").lower()
    if source == "github":
        stars = float(doc.get("raw_score") or doc.get("score") or 0.0)
        return 0.8 + min(0.7, stars / 400.0)
    if source == "news":
        return 1.0
    claps = float(doc.get("claps") or doc.get("raw_score") or 0.0)
    return 1.0 + min(0.3, claps / 200.0)


def score_categories(docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts: dict[str, float] = {cat: 0.0 for cat in RADAR_CATEGORIES}
    for doc in docs:
        text = ((doc.get("title") or "") + " " + (doc.get("summary") or "")).lower()
        base = SOURCE_WEIGHTS.get((doc.get("source") or "").lower(), 1.0)
        weight = base * doc_weight(doc)
        for category, keywords in RADAR_CATEGORIES.items():
            if any(keyword in text for keyword in keywords):
                counts[category] += weight

    max_count = max(counts.values(), default=0.0)
    if max_count <= 0:
        return [{"name": category, "value": 50} for category in RADAR_CATEGORIES]

    floor = 30.0
    return [
        {
            "name": category,
            "value": round(floor + (count / max_count) * (100.0 - floor)),
        }
        for category, count in counts.items()
    ]


def today_local() -> date:
    tz_cst = timezone(timedelta(hours=8))
    return datetime.now(tz_cst).date()


def compute_board_status(snapshot_date_str: str) -> dict[str, bool]:
    tz_cst = timezone(timedelta(hours=8))
    now_cst = datetime.now(tz_cst)
    today = now_cst.date()
    yesterday = today - timedelta(days=1)

    try:
        query_date = date.fromisoformat(snapshot_date_str)
    except ValueError:
        query_date = today

    if query_date == today:
        return {"is_finalized": False, "is_embargoed": False}
    if query_date == yesterday:
        if now_cst.hour < FINALIZE_HOUR:
            return {"is_finalized": False, "is_embargoed": True}
        return {"is_finalized": True, "is_embargoed": False}
    if query_date < yesterday:
        return {"is_finalized": True, "is_embargoed": False}
    return {"is_finalized": False, "is_embargoed": False}


def is_finalized(snapshot_date_str: str) -> bool:
    return compute_board_status(snapshot_date_str)["is_finalized"]


def is_embargoed(snapshot_date_str: str) -> bool:
    return compute_board_status(snapshot_date_str)["is_embargoed"]


def compute_source_board_status(
    snapshot_date_str: str, source: str
) -> SourceBoardStatus:
    """按源自然日界计算单源榜单状态（draft/embargoed/finalized）。

    与 compute_board_status 的整榜口径并存：整榜继续充当既有可见性
    闸门（行为不变），本函数产出分源契约，供后续分源可见性切换与前端
    状态提示消费。未知源回退旧版整榜时刻（FINALIZE_HOUR），保持保守。
    """
    boundary = SOURCE_DAY_BOUNDARY.get(source, DEFAULT_SOURCE_DAY_BOUNDARY)
    hour = SOURCE_FINALIZE_HOUR.get(source, FINALIZE_HOUR)
    tz_cst = timezone(timedelta(hours=8))
    now_cst = datetime.now(tz_cst)
    today = now_cst.date()
    yesterday = today - timedelta(days=1)

    try:
        query_date = date.fromisoformat(snapshot_date_str)
    except ValueError:
        query_date = today

    status: SourceBoardStatus = {
        "is_finalized": False,
        "is_embargoed": False,
        "day_boundary": boundary,
        "finalize_hour": hour,
        "is_disabled": False,
    }
    if query_date == today:
        return status
    if query_date == yesterday:
        if now_cst.hour < hour:
            status["is_embargoed"] = True
        else:
            status["is_finalized"] = True
        return status
    if query_date < yesterday:
        status["is_finalized"] = True
    return status


def compute_source_status_map(
    snapshot_date_str: str,
) -> dict[str, SourceBoardStatus]:
    """全部已注册源的分源状态 map（key 顺序固定，便于契约测试与前端遍历）。

    可插拔源被特性开关关闭时标记 is_disabled=True（其余字段照常计算），
    消费端据此隐藏或降级该源入口。
    """
    from backend.app.core.config import settings

    disabled_sources: set[str] = set()
    if not getattr(settings, "x_source_enabled", False):
        disabled_sources.add("x")
    status_map: dict[str, SourceBoardStatus] = {}
    for source in SOURCE_FINALIZE_HOUR:
        status = compute_source_board_status(snapshot_date_str, source)
        status["is_disabled"] = source in disabled_sources
        status_map[source] = status
    return status_map


def dedupe_docs(docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: dict[str, bool] = {}
    deduped: list[dict[str, Any]] = []
    for doc in docs:
        key = doc.get("url") or doc.get("title") or ""
        if key and key in seen:
            continue
        if key:
            seen[key] = True
        deduped.append(doc)
    return deduped


def resolve_snapshot_date(date_param: str | None) -> str:
    if date_param:
        return date_param
    return today_local().isoformat()


DEFAULT_SNAPSHOT_LOOKBACK_DAYS = 7


class SnapshotDateResolution(TypedDict):
    """看板展示日期解析结果：请求意图 vs 实际服务日期。

    stale=True 仅出现在默认视图（未传 date）回溯到更早有快照日期时；
    显式 date 参数永不回溯，requested 恒等于 resolved，stale 恒为 False。
    """

    requested_date: str
    resolved_date: str
    stale: bool


def build_date_resolution(requested: str, resolved: str) -> SnapshotDateResolution:
    return {
        "requested_date": requested,
        "resolved_date": resolved,
        # ISO YYYY-MM-DD 定长零填充，字符串序即日期序
        "stale": resolved < requested,
    }


def resolve_default_snapshot_date(
    available_dates_desc: Sequence[str],
    *,
    today: date | None = None,
    lookback_days: int = DEFAULT_SNAPSHOT_LOOKBACK_DAYS,
) -> str | None:
    """默认视图（未传 date）的回溯目标：窗口内最近一个 ≤ today 的快照日期。

    窗口含今天共 lookback_days 天；未来日期与不可解析项跳过。找不到
    返回 None——由调用方退回 today，照常服务当日的空榜/静默期语义。
    """
    current = today or today_local()
    window_start = current - timedelta(days=max(1, int(lookback_days)) - 1)
    best: date | None = None
    for raw in available_dates_desc:
        try:
            candidate = date.fromisoformat(str(raw))
        except ValueError:
            continue
        if not window_start <= candidate <= current:
            continue
        if best is None or candidate > best:
            best = candidate
    return best.isoformat() if best is not None else None
