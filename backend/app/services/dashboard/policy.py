from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
from typing import Any

from starlette.requests import Request

from backend.app.services.papers.presentation import public_base_url

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


def enrich_doc_pdf_url(doc: dict[str, Any], request: Request) -> dict[str, Any]:
    local_path = doc.get("local_pdf_path") or ""
    if local_path:
        filename = os.path.basename(local_path)
        # origin 只来自 PUBLIC_BASE_URL 配置（未配置则相对路径）；
        # Host / X-Forwarded-Proto 一律不采信，防伪造头污染缓存响应。
        doc["pdf_media_url"] = f"{public_base_url(request)}/api/media/papers/{filename}"
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
