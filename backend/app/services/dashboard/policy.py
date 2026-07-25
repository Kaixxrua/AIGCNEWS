from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
from typing import Any

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
}

PRODUCTHUNT_PERIOD_CHANNELS = {
    "daily": "producthunt_daily_html",
    "weekly": "producthunt_weekly_html",
    "monthly": "producthunt_monthly_html",
}

HACKERNEWS_PERIOD_CHANNELS = {
    "daily": "hn_daily_html",
    "weekly": "hn_weekly_html",
    "monthly": "hn_monthly_html",
}

PERIOD_WINDOW_DAYS = {"daily": 1, "weekly": 7, "monthly": 30}

ARXIV_PERIOD_CHANNELS = {
    "daily": "huggingface_daily_html",
    "weekly": "huggingface_weekly_html",
    "monthly": "huggingface_monthly_html",
}

ARXIV_ACCEPTED_CHANNELS = {
    "huggingface_daily_html",
    "huggingface_weekly_html",
    "huggingface_monthly_html",
    "",
}

GITHUB_PERIOD_CHANNELS = {
    "daily": "github_trending_daily",
    "weekly": "github_trending_weekly",
    "monthly": "github_trending_monthly",
}

GITHUB_ACCEPTED_CHANNELS = {
    "github_trending_daily",
    "github_trending_weekly",
    "github_trending_monthly",
    "github_hot_daily",
    "github_hot_weekly",
    "github_hot_monthly",
    "github_fallback",
    "",
}

FINALIZE_HOUR = 15


def enrich_doc_pdf_url(doc: dict[str, Any], request: Request) -> dict[str, Any]:
    local_path = doc.get("local_pdf_path") or ""
    if local_path:
        filename = os.path.basename(local_path)
        base_url = str(request.base_url).rstrip("/")
        forwarded_proto = request.headers.get("x-forwarded-proto", "")
        if forwarded_proto:
            base_url = base_url.replace("http://", f"{forwarded_proto}://", 1)
        doc["pdf_media_url"] = f"{base_url}/api/media/papers/{filename}"
    else:
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


def doc_date(doc: dict[str, Any], use_created_at: bool = False) -> str:
    if use_created_at:
        return str(doc.get("created_at") or doc.get("published_date") or "")[:10]
    return str(doc.get("published_date") or doc.get("created_at") or "")[:10]


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


def within_period(
    doc: dict[str, Any], period: str, reference_date: date | None = None
) -> bool:
    return within_period_extended(doc, period, extra_days=0, reference_date=reference_date)


def within_period_extended(
    doc: dict[str, Any],
    period: str,
    extra_days: int = 0,
    reference_date: date | None = None,
) -> bool:
    source = (doc.get("source") or "").lower()
    value = doc_date(doc, use_created_at=source == "arxiv")
    if not value:
        return True

    try:
        doc_day = datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            doc_day = date.fromisoformat(value[:10])
        except ValueError:
            return True

    window_days = PERIOD_WINDOW_DAYS.get(period, 1)
    base_date = reference_date or today_local()
    return doc_day >= (base_date - timedelta(days=window_days - 1 + extra_days))


def filter_docs_by_period(
    docs: list[dict[str, Any]],
    period: str,
    reference_date: date | None = None,
) -> list[dict[str, Any]]:
    arxiv_exact_channel = ARXIV_PERIOD_CHANNELS.get(period, "huggingface_daily_html")
    github_exact_channel = GITHUB_PERIOD_CHANNELS.get(period, "github_hot_daily")
    producthunt_exact_channel = PRODUCTHUNT_PERIOD_CHANNELS.get(
        period, PRODUCTHUNT_PERIOD_CHANNELS["daily"]
    )
    hackernews_exact_channel = HACKERNEWS_PERIOD_CHANNELS.get(
        period, HACKERNEWS_PERIOD_CHANNELS["daily"]
    )

    def channel_priority(source: str, channel: str) -> int:
        if source == "arxiv":
            if channel == arxiv_exact_channel:
                return 0
            if channel.startswith("huggingface_") or channel == "":
                return 1
            return 2
        if source == "github":
            if channel == github_exact_channel:
                return 0
            if channel in GITHUB_ACCEPTED_CHANNELS or channel.startswith("github_"):
                return 1
            return 2
        if source == "news":
            if channel.startswith("rss_") or channel.endswith("_rss") or channel == "":
                return 0
            return 2
        if source == "producthunt":
            if channel == producthunt_exact_channel:
                return 0
            if channel.startswith("producthunt_") or channel == "":
                return 1
            return 2
        if source == "hackernews":
            if channel == hackernews_exact_channel:
                return 0
            if channel.startswith("hn_") or channel == "":
                return 1
            return 2
        return 0

    by_source: dict[str, list[dict[str, Any]]] = {}
    for doc in docs:
        source = (doc.get("source") or "unknown").lower()
        by_source.setdefault(source, []).append(doc)

    result: list[dict[str, Any]] = []
    for source, source_docs in by_source.items():
        exact_docs: list[dict[str, Any]] = []
        fallback_docs: list[dict[str, Any]] = []
        for doc in source_docs:
            channel = doc.get("source_channel") or doc.get("channel") or ""
            priority = channel_priority(source, channel)
            if priority == 0:
                exact_docs.append(doc)
            elif priority == 1:
                fallback_docs.append(doc)

        min_count = 5 if period == "daily" else 3

        def pick_with_time(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
            if not candidates:
                return []
            for extra in range(0, 15):
                filtered = [
                    doc
                    for doc in candidates
                    if within_period_extended(
                        doc, period, extra, reference_date=reference_date
                    )
                ]
                if len(filtered) >= min_count:
                    return filtered
            return candidates

        if exact_docs:
            result.extend(exact_docs)
        elif fallback_docs:
            result.extend(pick_with_time(fallback_docs))

    def sort_key(doc: dict[str, Any]) -> tuple[int, float]:
        source = (doc.get("source") or "").lower()
        rank = int(doc.get("rank_in_period") or 9999)
        score = float(doc.get("raw_score") or doc.get("score") or 0)
        if source == "github":
            return (rank, -score)
        return (9999, -score)

    result.sort(key=sort_key)
    return result


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
