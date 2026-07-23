from __future__ import annotations

import asyncio
import hashlib
import json
import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi_cache.decorator import cache

from backend.app.api.dependencies import (
    get_document_repository,
    get_rank_snapshot_repository,
    get_user_account_repository,
)
from backend.app.repositories.document_repository import DocumentStatisticsReader
from backend.app.repositories.rank_snapshot_repository import RankSnapshotReader
from backend.app.repositories.user_account_repository import UserStatisticsReader

router = APIRouter()


def _enrich_doc_pdf_url(doc: Dict[str, Any], request: Request) -> Dict[str, Any]:
    """将 local_pdf_path 相对路径转换为完整的可访问媒体 URL。

    例如：
        local_pdf_path = "storage/papers/2403.12345.pdf"
        → pdf_media_url = "https://host/api/media/papers/2403.12345.pdf"

    通过 X-Forwarded-Proto 头感知真实协议（HTTPS），避免 Mixed Content 问题。
    如果 local_pdf_path 为空，pdf_media_url 为 None。
    """
    local_path = doc.get("local_pdf_path") or ""
    if local_path:
        filename = os.path.basename(local_path)
        base_url = str(request.base_url).rstrip("/")
        # 读取 Nginx 传入的真实协议头，感知 HTTPS
        forwarded_proto = request.headers.get("x-forwarded-proto", "")
        if forwarded_proto:
            base_url = base_url.replace("http://", f"{forwarded_proto}://", 1)
        doc["pdf_media_url"] = f"{base_url}/api/media/papers/{filename}"
    else:
        doc["pdf_media_url"] = None
    return doc


def _dashboard_cache_key_builder(
    func,
    namespace: str = "",
    request: Request | None = None,
    response: Response | None = None,
    *args,
    **kwargs,
) -> str:
    """为 dashboard 接口构建稳定 cache key，确保 date/period/source/limit 等参数隔离。

    关键修复：当 date 参数未传入时，显式注入 CST 当天日期到 key 中，
    防止跨日后命中前一天缓存（原先无 date 参数时 key 完全相同）。
    """
    from datetime import datetime, timezone, timedelta

    query_params = dict(request.query_params) if request is not None else {}

    # 若未传 date 参数，注入今日 CST 日期，确保每天 key 不同
    if "date" not in query_params:
        tz_cst = timezone(timedelta(hours=8))
        query_params["_date_injected"] = datetime.now(tz_cst).strftime("%Y-%m-%d")

    payload = {
        "path": request.url.path if request is not None else func.__name__,
        "namespace": namespace,
        "query": query_params,
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    digest = hashlib.md5(raw.encode("utf-8")).hexdigest()
    return f"{namespace}:{func.__name__}:{digest}"


# -----------------------------------------------------------------------
# Helper: compute trend radar data from top documents (multi-source weighted)
# -----------------------------------------------------------------------

_RADAR_CATEGORIES = {
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

_SOURCE_WEIGHTS: Dict[str, float] = {
    "arxiv": 1.0,
    "github": 1.0,
    "news": 1.0,
    "producthunt": 1.0,
    "hackernews": 1.0,
}

_PH_PERIOD_CHANNELS = {
    "daily": "producthunt_daily_html",
    "weekly": "producthunt_weekly_html",
    "monthly": "producthunt_monthly_html",
}

_HN_PERIOD_CHANNELS = {
    "daily": "hn_daily_html",
    "weekly": "hn_weekly_html",
    "monthly": "hn_monthly_html",
}

_PERIOD_WINDOW_DAYS = {
    "daily": 1,
    "weekly": 7,
    "monthly": 30,
}

# arxiv 各周期对应的 channel（按优先级排序，daily 也接受 weekly channel 数据）
_ARXIV_PERIOD_CHANNELS = {
    "daily": "huggingface_daily_html",
    "weekly": "huggingface_weekly_html",
    "monthly": "huggingface_monthly_html",
}

# arxiv 每个周期接受的所有 channel（宽泛匹配，有任何 hf channel 或空 channel 都算）
_ARXIV_ACCEPTED_CHANNELS: set = {
    "huggingface_daily_html",
    "huggingface_weekly_html",
    "huggingface_monthly_html",
    "",  # 兼容旧数据（空 channel）
}

_GITHUB_PERIOD_CHANNELS = {
    "daily": "github_trending_daily",
    "weekly": "github_trending_weekly",
    "monthly": "github_trending_monthly",
}

# GitHub 每个周期接受的 channel（宽泛匹配，兼容旧数据）
_GITHUB_ACCEPTED_CHANNELS: set = {
    "github_trending_daily",
    "github_trending_weekly",
    "github_trending_monthly",
    # 兼容旧 hot 算法数据
    "github_hot_daily",
    "github_hot_weekly",
    "github_hot_monthly",
    "github_fallback",
    "",
}


def _doc_weight(doc: Dict[str, Any]) -> float:
    """按来源做轻量归一化，输出区间约 [0.8, 1.5] 的文档权重。"""
    source = (doc.get("source") or "arxiv").lower()

    if source == "github":
        stars = float(doc.get("raw_score") or doc.get("score") or 0.0)
        return 0.8 + min(0.7, stars / 400.0)

    if source == "news":
        return 1.0

    claps = float(doc.get("claps") or doc.get("raw_score") or 0.0)
    return 1.0 + min(0.3, claps / 200.0)


def _score_categories(docs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    counts: Dict[str, float] = {cat: 0.0 for cat in _RADAR_CATEGORIES}

    for doc in docs:
        text = ((doc.get("title") or "") + " " + (doc.get("summary") or "")).lower()
        base = _SOURCE_WEIGHTS.get((doc.get("source") or "").lower(), 1.0)
        weight = base * _doc_weight(doc)

        for cat, keywords in _RADAR_CATEGORIES.items():
            if any(kw in text for kw in keywords):
                counts[cat] += weight

    max_count = max(counts.values(), default=0.0)
    if max_count <= 0:
        return [{"name": cat, "value": 50} for cat in _RADAR_CATEGORIES]

    floor = 30.0
    return [
        {
            "name": cat,
            "value": round(floor + (cnt / max_count) * (100.0 - floor)),
        }
        for cat, cnt in counts.items()
    ]


def _doc_date(doc: Dict[str, Any], use_created_at: bool = False) -> str:
    """返回文档的日期字符串（取前10位）。

    对于 arxiv 来源，论文的 published_date 是论文发表时间（可能是数天前），
    应使用 created_at（数据库采集入库时间）来判断是否属于今日/本周等周期。
    """
    if use_created_at:
        return str(doc.get("created_at") or doc.get("published_date") or "")[:10]
    return str(doc.get("published_date") or doc.get("created_at") or "")[:10]


def _today_local() -> "date":
    """返回用户本地时区（Asia/Shanghai, UTC+8）的今天日期，避免服务器 UTC 时差问题。"""
    from datetime import datetime, timezone, timedelta, date

    tz_cst = timezone(timedelta(hours=8))
    return datetime.now(tz_cst).date()


# 定榜 / 静默期时间：UTC+8 下午 15:00
_FINALIZE_HOUR = 15


def _compute_board_status(snapshot_date_str: str) -> dict:
    """计算指定日期的榜单状态（is_finalized / is_embargoed）。

    核心逻辑（全局时间基准：UTC+8 北京时间）：
      - 查询今天 (today):
          is_finalized=False, is_embargoed=False → 展示实时动态初榜
      - 查询昨天 (yesterday):
          * 当前 0:00-14:59: is_finalized=False, is_embargoed=True → 静默期，拦截隐藏
          * 当前 15:00+:     is_finalized=True,  is_embargoed=False → 已定榜
      - 查询更早历史 (before yesterday):
          is_finalized=True, is_embargoed=False → 已定榜
      - 查询未来日期:
          is_finalized=False, is_embargoed=False → 无数据
    """
    from datetime import datetime, timezone, timedelta, date as _date_type

    tz_cst = timezone(timedelta(hours=8))
    now_cst = datetime.now(tz_cst)
    today = now_cst.date()
    yesterday = today - timedelta(days=1)

    try:
        query_date = _date_type.fromisoformat(snapshot_date_str)
    except ValueError:
        query_date = today

    if query_date == today:
        # 今天：实时动态初榜，永远不定榜
        return {"is_finalized": False, "is_embargoed": False}

    if query_date == yesterday:
        # 昨天：15:00 前静默期，15:00 后解禁并定榜
        if now_cst.hour < _FINALIZE_HOUR:
            return {"is_finalized": False, "is_embargoed": True}
        else:
            return {"is_finalized": True, "is_embargoed": False}

    if query_date < yesterday:
        # 更早的历史：已定榜
        return {"is_finalized": True, "is_embargoed": False}

    # 未来日期
    return {"is_finalized": False, "is_embargoed": False}


def _is_finalized(snapshot_date_str: str) -> bool:
    """向后兼容：判断指定日期是否已定榜。"""
    return _compute_board_status(snapshot_date_str)["is_finalized"]


def _is_embargoed(snapshot_date_str: str) -> bool:
    """判断指定日期是否处于静默期（数据不可见）。"""
    return _compute_board_status(snapshot_date_str)["is_embargoed"]


def _within_period(
    doc: Dict[str, Any], period: str, reference_date: Optional["date"] = None
) -> bool:
    return _within_period_extended(
        doc, period, extra_days=0, reference_date=reference_date
    )


def _within_period_extended(
    doc: Dict[str, Any],
    period: str,
    extra_days: int = 0,
    reference_date: Optional["date"] = None,
) -> bool:
    """检查文档是否在指定周期窗口内（可额外放宽 extra_days 天，用于兜底回退）。

    对 arxiv 来源使用 created_at（入库时间）而非 published_date（论文发表时间），
    因为 HuggingFace Daily Papers 中的论文发表时间可能是数天前。

    Args:
        reference_date: 时间窗口基准日期。查询历史日期时应传入用户选择的日期，
                        而非默认的"今天"，避免历史查询返回当天数据。
    """
    from datetime import date, datetime, timedelta

    source = (doc.get("source") or "").lower()
    # arxiv 论文的 published_date 是原始发表时间，用 created_at 判断采集周期更准确
    use_ingestion_time = source == "arxiv"
    value = _doc_date(doc, use_created_at=use_ingestion_time)
    if not value:
        return True

    try:
        doc_day = datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            doc_day = date.fromisoformat(value[:10])
        except ValueError:
            return True

    window_days = _PERIOD_WINDOW_DAYS.get(period, 1)
    base_date = reference_date or _today_local()
    return doc_day >= (base_date - timedelta(days=window_days - 1 + extra_days))


def _filter_docs_by_period(
    docs: List[Dict[str, Any]],
    period: str,
    reference_date: Optional["date"] = None,
) -> List[Dict[str, Any]]:
    """按周期和来源过滤文档，使用 rank_in_period 排序（三榜互不影响）。

    核心设计（rank_in_period 方案）：
    - arxiv/github：采集时每篇论文记录了其在当前榜单中的名次（rank_in_period=1,2,3...）
      查询时精确匹配当前 period 的 source_channel，按 rank_in_period 升序排列。
      这样日/周/月榜的 upvotes 数量级差异完全不影响排序。
    - 其他来源：同样按精确 channel + rank_in_period 排序，fallback 到时间窗口。
    """

    # 各来源当前 period 的精确 channel
    arxiv_exact_channel = _ARXIV_PERIOD_CHANNELS.get(period, "huggingface_daily_html")
    github_exact_channel = _GITHUB_PERIOD_CHANNELS.get(period, "github_hot_daily")
    ph_exact_channel = _PH_PERIOD_CHANNELS.get(period, _PH_PERIOD_CHANNELS["daily"])
    hn_exact_channel = _HN_PERIOD_CHANNELS.get(period, _HN_PERIOD_CHANNELS["daily"])

    def _channel_priority(source: str, channel: str) -> int:
        """返回 channel 的优先级：0=精确匹配，1=宽泛匹配，2=不匹配（排除）"""
        if source == "arxiv":
            if channel == arxiv_exact_channel:
                return 0
            if channel.startswith("huggingface_") or channel == "":
                return 1  # fallback：其他榜期数据
            return 2
        if source == "github":
            if channel == github_exact_channel:
                return 0
            if channel in _GITHUB_ACCEPTED_CHANNELS or channel.startswith("github_"):
                return 1
            return 2
        if source == "news":
            if channel.startswith("rss_") or channel.endswith("_rss") or channel == "":
                return 0
            return 2
        if source == "producthunt":
            if channel == ph_exact_channel:
                return 0
            if channel.startswith("producthunt_") or channel == "":
                return 1
            return 2
        if source == "hackernews":
            if channel == hn_exact_channel:
                return 0
            if channel.startswith("hn_") or channel == "":
                return 1
            return 2
        return 0  # 其他来源不做 channel 过滤

    # 按来源分组
    by_source: Dict[str, List[Dict[str, Any]]] = {}
    for doc in docs:
        src = (doc.get("source") or "unknown").lower()
        by_source.setdefault(src, []).append(doc)

    result: List[Dict[str, Any]] = []

    for src, src_docs in by_source.items():
        # 按 channel 优先级分组
        exact_docs: List[Dict[str, Any]] = []
        fallback_docs: List[Dict[str, Any]] = []
        for d in src_docs:
            ch = d.get("source_channel") or d.get("channel") or ""
            prio = _channel_priority(src, ch)
            if prio == 0:
                exact_docs.append(d)
            elif prio == 1:
                fallback_docs.append(d)

        min_count = 5 if period == "daily" else 3

        def _try_pick_with_time(
            candidates: List[Dict[str, Any]],
        ) -> List[Dict[str, Any]]:
            """时间窗口回退策略（适用于无 rank_in_period 的数据）。"""
            if not candidates:
                return []
            for extra in range(0, 15):
                filtered = [
                    d
                    for d in candidates
                    if _within_period_extended(
                        d, period, extra, reference_date=reference_date
                    )
                ]
                if len(filtered) >= min_count:
                    return filtered
            return candidates

        if exact_docs:
            # 精确匹配到当前 period channel：直接用，按 rank_in_period 升序
            # rank_in_period 是采集时记录的榜单名次，无需时间窗口过滤（channel 已保证正确性）
            result.extend(exact_docs)
        elif fallback_docs:
            # 无精确匹配时回退到其他 channel，需按时间窗口过滤
            picked = _try_pick_with_time(fallback_docs)
            result.extend(picked)

    # 排序规则：
    #   - github 源：优先按 rank_in_period 升序（原始榜单顺序），raw_score 作为次要
    #   - 其他来源：优先按 raw_score（vote/star 数）降序，rank_in_period 作为次要
    def _sort_key(d: Dict[str, Any]) -> tuple:
        src = (d.get("source") or "").lower()
        rank = int(d.get("rank_in_period") or 9999)
        score = float(d.get("raw_score") or d.get("score") or 0)
        if src == "github":
            return (rank, -score)
        return (9999, -score)

    result.sort(key=_sort_key)
    return result


def _dedupe_docs(docs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """去重：同一 URL/标题的文档只保留第一条（已按优先级排序）。"""
    seen: dict = {}
    deduped: List[Dict[str, Any]] = []
    for doc in docs:
        key = doc.get("url") or doc.get("title") or ""
        if key and key in seen:
            continue
        if key:
            seen[key] = True
        deduped.append(doc)
    return deduped


def _resolve_snapshot_date(date_param: Optional[str]) -> str:
    """解析 date 参数，返回 YYYY-MM-DD 字符串。未传入时返回 CST 当天日期。"""
    if date_param:
        return date_param
    return _today_local().isoformat()


def _apply_hn_daily_dedup(
    db: RankSnapshotReader,
    date_str: str,
    docs: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """对 HackerNews 日榜做特殊处理：排除昨日已上榜的条目，按 points（raw_score）降序。

    规则：
      - 只处理 source='hackernews' 的文档，其他来源原样保留
      - 查询昨日 hn_daily_html 快照中的 doc_id 集合
      - 今日 HN 数据中，凡是昨日已存在的 doc_id 一律排除
      - 剩余条目按 raw_score（即 HN points）从高到低排序
    """
    from datetime import date, timedelta

    # 分离 HN 文档和其他文档
    hn_docs: List[Dict[str, Any]] = []
    other_docs: List[Dict[str, Any]] = []
    for d in docs:
        if (d.get("source") or "").lower() == "hackernews":
            hn_docs.append(d)
        else:
            other_docs.append(d)

    if not hn_docs:
        return docs

    # 计算昨日日期
    try:
        current_date = date.fromisoformat(date_str)
    except ValueError:
        current_date = _today_local()
    yesterday_str = (current_date - timedelta(days=1)).isoformat()

    # 获取昨日 HN 快照中的 doc_id 集合
    hn_channel = _HN_PERIOD_CHANNELS.get("daily", "hn_daily_html")
    yesterday_ids = db.get_snapshot_doc_ids(
        snapshot_date=yesterday_str,
        source_channel=hn_channel,
    )

    # 排除昨日已上榜的条目
    if yesterday_ids:
        before_count = len(hn_docs)
        hn_docs = [d for d in hn_docs if d.get("id") not in yesterday_ids]
        excluded = before_count - len(hn_docs)
        if excluded > 0:
            import logging

            logging.getLogger(__name__).info(
                "[HN Daily] 排除昨日(%s)已上榜条目 %d 条，剩余 %d 条",
                yesterday_str,
                excluded,
                len(hn_docs),
            )

    # HN 日榜按 raw_score（points）从高到低排序
    hn_docs.sort(
        key=lambda d: float(d.get("raw_score") or d.get("score") or 0),
        reverse=True,
    )

    # 合并：其他来源文档 + 去重后的 HN 文档
    return other_docs + hn_docs


def _get_docs_for_date(
    db: RankSnapshotReader,
    date_str: str,
    period: str,
    source_type: Optional[str] = None,
    limit: int = 500,
) -> List[Dict[str, Any]]:
    """从快照表获取指定日期 + 周期的文档，严格按 period 对应的 channel 查询。

    数据物理隔离原则：日榜只查 daily channel，周榜只查 weekly channel，
    月榜只查 monthly channel。如果对应 channel 无数据则返回空列表，
    绝不跨周期降级（宁缺毋乱）。

    返回按 rank_in_period 升序排列的文档列表。
    """
    # 构造当前 period 对应的精确 source_channel 映射
    channel_maps: Dict[str, Dict[str, str]] = {
        "arxiv": _ARXIV_PERIOD_CHANNELS,
        "github": _GITHUB_PERIOD_CHANNELS,
        "news": {
            "daily": "techmeme_daily_rss",
            "weekly": "techmeme_daily_rss",
            "monthly": "techmeme_daily_rss",
        },
        "producthunt": _PH_PERIOD_CHANNELS,
        "hackernews": _HN_PERIOD_CHANNELS,
    }

    # 同周期备用 channel（仅限同一 period 的历史兼容 channel，绝不跨周期）
    _SAME_PERIOD_FALLBACKS: Dict[str, Dict[str, List[str]]] = {
        "github": {
            "daily": ["github_hot_daily", "github_fallback"],
            "weekly": ["github_hot_weekly"],
            "monthly": ["github_hot_monthly"],
        },
    }

    all_snapshot_docs: List[Dict[str, Any]] = []

    if source_type and source_type != "all":
        # ── 单来源查询：严格精确 channel ──
        ch_map = channel_maps.get(source_type, {})
        channel = ch_map.get(period)
        if channel:
            docs = db.get_snapshot_documents(
                snapshot_date=date_str,
                source_channel=channel,
                source_type=source_type,
                limit=limit,
            )
            all_snapshot_docs.extend(docs)

        # 精确 channel 无数据时，仅尝试同周期备用 channel（不跨周期）
        if not all_snapshot_docs:
            fallbacks = _SAME_PERIOD_FALLBACKS.get(source_type, {}).get(period, [])
            for fb_channel in fallbacks:
                docs = db.get_snapshot_documents(
                    snapshot_date=date_str,
                    source_channel=fb_channel,
                    source_type=source_type,
                    limit=limit,
                )
                if docs:
                    all_snapshot_docs.extend(docs)
                    break  # 找到即停，不贪多
    else:
        # ── 全来源查询：逐来源按精确 channel 拉取，严格隔离 ──
        for src, ch_map in channel_maps.items():
            channel = ch_map.get(period)
            if not channel:
                continue
            docs = db.get_snapshot_documents(
                snapshot_date=date_str,
                source_channel=channel,
                source_type=src,
                limit=limit,
            )
            if docs:
                all_snapshot_docs.extend(docs)
                continue
            # 该来源精确 channel 无数据，尝试同周期备用 channel
            fallbacks = _SAME_PERIOD_FALLBACKS.get(src, {}).get(period, [])
            for fb_channel in fallbacks:
                docs = db.get_snapshot_documents(
                    snapshot_date=date_str,
                    source_channel=fb_channel,
                    source_type=src,
                    limit=limit,
                )
                if docs:
                    all_snapshot_docs.extend(docs)
                    break

    if all_snapshot_docs:
        # ── HackerNews 日榜特殊处理：排除昨日已上榜的条目，按 points 降序 ──
        if period == "daily":
            all_snapshot_docs = _apply_hn_daily_dedup(db, date_str, all_snapshot_docs)
        return all_snapshot_docs

    # ── 无快照数据 → 返回空列表（宁缺毋乱） ──
    # 前端根据 is_finalized / is_embargoed 和列表是否为空来展示合适的提示
    return []


@router.get("/dashboard/top")
@cache(expire=3600, namespace="dashboard", key_builder=_dashboard_cache_key_builder)
async def get_top_list(
    request: Request,
    limit: int = Query(default=10, ge=1, le=50),
    source: Optional[str] = Query(
        default=None, description="过滤来源：all/arxiv/github/news"
    ),
    period: str = Query(default="daily", pattern="^(daily|weekly|monthly)$"),
    date: Optional[str] = Query(
        default=None, description="快照日期 YYYY-MM-DD，不传默认今天"
    ),
    rank_snapshots: RankSnapshotReader = Depends(get_rank_snapshot_repository),
):
    """Return top-N documents ranked by vote count, optionally filtered by source, period and date."""
    source_type = None if (not source or source == "all") else source
    snapshot_date = _resolve_snapshot_date(date)

    board = _compute_board_status(snapshot_date)

    # 静默期拦截：直接返回空列表，防止前端泄露未解禁数据
    if board["is_embargoed"]:
        return {
            "items": [],
            "total": 0,
            "period": period,
            "snapshot_date": snapshot_date,
            "is_finalized": board["is_finalized"],
            "is_embargoed": True,
        }

    docs = await asyncio.to_thread(
        _get_docs_for_date, rank_snapshots, snapshot_date, period, source_type, 500
    )
    deduped = _dedupe_docs(docs)
    top_items = deduped[:limit]

    # 模块四-1：为每条文档注入完整 pdf_media_url
    top_items = [_enrich_doc_pdf_url(dict(doc), request) for doc in top_items]

    return {
        "items": top_items,
        "total": len(top_items),
        "period": period,
        "snapshot_date": snapshot_date,
        "is_finalized": board["is_finalized"],
        "is_embargoed": False,
    }


@router.get("/dashboard/radar")
@cache(expire=3600, namespace="dashboard", key_builder=_dashboard_cache_key_builder)
async def get_trend_radar(
    limit: int = Query(default=50, ge=10, le=200),
    source: Optional[str] = Query(
        default=None, description="过滤来源：all/arxiv/github/news"
    ),
    period: str = Query(default="daily", pattern="^(daily|weekly|monthly)$"),
    date: Optional[str] = Query(
        default=None, description="快照日期 YYYY-MM-DD，不传默认今天"
    ),
    rank_snapshots: RankSnapshotReader = Depends(get_rank_snapshot_repository),
):
    """Return trend radar chart data computed from filtered top documents."""
    source_type = None if (not source or source == "all") else source
    snapshot_date = _resolve_snapshot_date(date)

    board = _compute_board_status(snapshot_date)

    # 静默期拦截
    if board["is_embargoed"]:
        return {
            "radar": [],
            "doc_count": 0,
            "period": period,
            "snapshot_date": snapshot_date,
            "is_finalized": board["is_finalized"],
            "is_embargoed": True,
        }

    docs = await asyncio.to_thread(
        _get_docs_for_date,
        rank_snapshots,
        snapshot_date,
        period,
        source_type,
        max(limit, 100),
    )
    radar = _score_categories(docs[:limit])
    return {
        "radar": radar,
        "doc_count": len(docs[:limit]),
        "period": period,
        "snapshot_date": snapshot_date,
        "is_finalized": board["is_finalized"],
        "is_embargoed": False,
    }


@router.get("/dashboard/summary")
@cache(expire=3600, namespace="dashboard", key_builder=_dashboard_cache_key_builder)
async def get_dashboard_summary(
    request: Request,
    period: str = Query(default="daily", pattern="^(daily|weekly|monthly)$"),
    date: Optional[str] = Query(
        default=None, description="快照日期 YYYY-MM-DD，不传默认今天"
    ),
    user_statistics: UserStatisticsReader = Depends(get_user_account_repository),
    document_statistics: DocumentStatisticsReader = Depends(get_document_repository),
    rank_snapshots: RankSnapshotReader = Depends(get_rank_snapshot_repository),
):
    """Return a combined dashboard payload: period top-10 + radar + basic stats + source breakdown.

    当传入 date 参数时，从 document_rank_snapshots 表查询该日期的历史排行数据；
    未传入时默认查当天，若无快照则回退到原有 documents 表逻辑。
    """
    from datetime import timedelta, timezone as _tz

    snapshot_date = _resolve_snapshot_date(date)

    board = _compute_board_status(snapshot_date)

    # ── 今日独立访客数（Redis SET：visitor:{YYYY-MM-DD}）──────────
    async def _get_today_unique_visitors() -> int:
        redis_client = getattr(request.app.state, "redis", None)
        if redis_client is None:
            return 0
        tz_cst = _tz(timedelta(hours=8))
        from datetime import datetime as _dt

        today_key = f"visitor:{_dt.now(tz_cst).strftime('%Y-%m-%d')}"
        try:
            count = await redis_client.scard(today_key)
            return int(count or 0)
        except Exception:
            return 0

    # 静默期拦截：返回空排行数据，但统计卡片仍显示全库累计数量
    if board["is_embargoed"]:
        source_counts_embargo = await asyncio.to_thread(document_statistics.get_source_counts)
        total_embargo = sum(source_counts_embargo.values())
        registered_users = await asyncio.to_thread(user_statistics.get_user_count)
        today_registered_users = await asyncio.to_thread(
            user_statistics.get_today_registered_user_count
        )
        user_count = registered_users + today_registered_users
        return {
            "top_list": [],
            "radar": [],
            "stats": {
                "total_documents": total_embargo,
                "source_counts": source_counts_embargo,
                "registered_users": registered_users,
                "today_registered_users": today_registered_users,
                "user_count": user_count,
                "today_unique_visitors": user_count,
            },
            "period": period,
            "snapshot_date": snapshot_date,
            "is_finalized": board["is_finalized"],
            "is_embargoed": True,
        }

    docs = await asyncio.to_thread(
        _get_docs_for_date, rank_snapshots, snapshot_date, period, None, 500
    )
    deduped = _dedupe_docs(docs)
    top10 = deduped[:10]
    radar = _score_categories(deduped[:50])

    # ── 统计卡片数据 ──────────────────────────────────────────────
    # 始终使用全库累计统计，数字不随日期切换而变化，
    # 展示的是每个来源在数据库中的实际入库总量。
    source_counts = await asyncio.to_thread(document_statistics.get_source_counts)
    total_documents = sum(source_counts.values())
    registered_users = await asyncio.to_thread(user_statistics.get_user_count)
    today_registered_users = await asyncio.to_thread(user_statistics.get_today_registered_user_count)
    user_count = registered_users + today_registered_users
    today_new_documents = await asyncio.to_thread(document_statistics.get_today_document_count)

    return {
        "top_list": top10,
        "radar": radar,
        "stats": {
            "total_documents": total_documents,
            "source_counts": source_counts,
            "registered_users": registered_users,
            "today_registered_users": today_registered_users,
            "user_count": user_count,
            "today_new_documents": today_new_documents,
            "today_unique_visitors": user_count,
        },
        "period": period,
        "snapshot_date": snapshot_date,
        "is_finalized": board["is_finalized"],
        "is_embargoed": False,
    }


@router.get("/dashboard/snapshot-dates")
@cache(expire=60, namespace="dashboard", key_builder=_dashboard_cache_key_builder)
async def get_snapshot_dates(
    limit: int = Query(default=60, ge=1, le=365),
    source: Optional[str] = Query(default=None),
    period: Optional[str] = Query(default=None, pattern="^(daily|weekly|monthly)$"),
    rank_snapshots: RankSnapshotReader = Depends(get_rank_snapshot_repository),
):
    """返回指定来源和周期有快照记录的日期列表（降序）。"""
    source_type = None if (not source or source == "all") else source
    dates = await asyncio.to_thread(
        rank_snapshots.get_snapshot_dates,
        limit,
        source_type,
        period,
    )
    return {
        "dates": dates,
        "total": len(dates),
        "source": source_type or "all",
        "period": period,
    }


@router.get("/dashboard/visitor-count")
async def get_visitor_count(
    request: Request,
    user_statistics: UserStatisticsReader = Depends(get_user_account_repository),
):
    """返回用户数指标（不缓存，实时读取数据库）。"""
    registered_users = await asyncio.to_thread(user_statistics.get_user_count)
    today_registered_users = await asyncio.to_thread(user_statistics.get_today_registered_user_count)
    user_count = registered_users + today_registered_users
    return {
        "user_count": user_count,
        "registered_users": registered_users,
        "today_registered_users": today_registered_users,
        "today_unique_visitors": user_count,
    }


@router.get("/dashboard/github-hot")
@cache(expire=3600, namespace="dashboard", key_builder=_dashboard_cache_key_builder)
async def get_github_hot_list(
    period: str = Query(default="daily", pattern="^(daily|weekly|monthly)$"),
    limit: int = Query(default=10, ge=1, le=50),
):
    """Return GitHub hot repositories ranked by growth + baseline + age correction."""
    from backend.app.services.ingestion.github_hot_service import get_github_hot_rank

    result = await asyncio.to_thread(get_github_hot_rank, period, limit)
    return result
