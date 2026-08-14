"""存量视频封面回填：无 poster_url 的 video/animated_gif 推文。

前端对这类视频回退 /api/media/x/poster?url= 服务端抽帧端点——查询形态
边缘不可缓存（边缘 nginx 不解码 percent-encoded 目标 URL），每次都要
绕回源全链路，实测最坏 28.7s。回填在预热周期里直调抽帧领域件把磁盘
封面缓存提前生成，用户请求变成 FileResponse 直出。

直调 x_poster_frames.fetch_partial/extract_first_frame 绕开路由层匿名
限速（预热是内部任务，不涉及外部 IP 配额）；负标记 sidecar 提供跨重启
的免重试记忆（路由层 _poster_negative 仅 5 分钟内存 TTL，不够用）。
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.app.core.config import settings
from backend.app.repositories.document_repository import DocumentRecentReader
from backend.app.services import x_poster_frames
from backend.app.services.media_cache import enforce_cache_budget
from backend.app.services.x_media_urls import collect_poster_backfill_candidates
from backend.app.services.x_poster_frames import XMediaUpstreamError

logger = logging.getLogger(__name__)

_RECENT_LIMIT = 500

# 负标记 TTL：上游 404 = 推文/媒体已删，7 天内不重试（对齐媒体缓存留存期）；
# 抽帧失败多为损坏/非 faststart 源，24h 后值得再试；传输错误不写标记，
# 下一轮自然重试。
_MARKER_TTL_BY_REASON = {
    "upstream_404": timedelta(days=7),
    "extract_failed": timedelta(hours=24),
}


@dataclass(frozen=True)
class PosterBackfillResult:
    candidates: int
    attempted: int
    generated: int
    failed: int
    skipped_marker: int


def _marker_path(cache_path: Path) -> Path:
    return cache_path.with_name(f"{cache_path.stem}.failed")


def _write_marker(cache_path: Path, now: datetime, reason: str) -> None:
    try:
        _marker_path(cache_path).write_text(f"{now.isoformat()} {reason}")
    except OSError as exc:
        logger.warning("[XPosterBackfill] 负标记写入失败（非致命）: %s", exc)


def _fresh_marker_reason(cache_path: Path, now: datetime) -> str | None:
    """负标记仍在免重试期内则返回原因；坏标记不阻塞重试。"""
    try:
        text = _marker_path(cache_path).read_text().strip()
    except OSError:
        return None
    try:
        ts_raw, reason = text.split(" ", 1)
        marked_at = datetime.fromisoformat(ts_raw)
        ttl = _MARKER_TTL_BY_REASON[reason]
    except (ValueError, KeyError):
        return None
    if now - marked_at < ttl:
        return reason
    return None


async def backfill_missing_posters(
    documents: DocumentRecentReader,
    *,
    window_hours: int | None = None,
    max_per_run: int | None = None,
    now: datetime | None = None,
) -> PosterBackfillResult:
    """对滚动窗口内无 poster_url 的存量视频渐进生成磁盘封面缓存。

    单轮上限 max_per_run 控制代价（每条 = 4MB 回源 + ffmpeg 抽帧），
    随预热周期渐进消化存量；整轮不抛异常（调用方是采集后台任务）。
    """
    window_hours = (
        settings.x_media_warmup_window_hours if window_hours is None else window_hours
    )
    max_per_run = (
        settings.x_poster_backfill_max_per_run if max_per_run is None else max_per_run
    )
    now = now or datetime.now(timezone.utc)
    since_iso = (now - timedelta(hours=window_hours)).isoformat(timespec="seconds")
    docs = await asyncio.to_thread(
        documents.list_recent_by_source, "x", since_iso=since_iso, limit=_RECENT_LIMIT
    )
    candidates = collect_poster_backfill_candidates(docs)

    attempted = generated = failed = skipped_marker = 0
    budget_dirty = False
    for url in candidates:
        if attempted >= max_per_run:
            break
        cache_path = x_poster_frames.poster_cache_path(url)
        if cache_path.exists():
            continue
        if _fresh_marker_reason(cache_path, now) is not None:
            skipped_marker += 1
            continue
        attempted += 1
        try:
            partial = await x_poster_frames.fetch_partial(url)
        except XMediaUpstreamError as exc:
            failed += 1
            if exc.status_code == 404:
                _write_marker(cache_path, now, "upstream_404")
            continue
        except Exception as exc:  # noqa: BLE001 - 单条故障不影响整轮
            failed += 1
            logger.debug("[XPosterBackfill] %s 回源异常: %s", url, exc)
            continue
        if await x_poster_frames.extract_first_frame(partial, cache_path):
            generated += 1
            budget_dirty = True
        else:
            failed += 1
            _write_marker(cache_path, now, "extract_failed")

    if budget_dirty:
        await enforce_cache_budget(
            x_poster_frames.poster_cache_dir(),
            max_bytes=settings.media_cache_max_bytes,
            max_age_seconds=settings.media_cache_max_age_seconds,
        )

    result = PosterBackfillResult(
        candidates=len(candidates),
        attempted=attempted,
        generated=generated,
        failed=failed,
        skipped_marker=skipped_marker,
    )
    logger.info(
        "[XPosterBackfill] 回填完成：candidates=%d attempted=%d generated=%d "
        "failed=%d skipped_marker=%d",
        result.candidates,
        result.attempted,
        result.generated,
        result.failed,
        result.skipped_marker,
    )
    return result
