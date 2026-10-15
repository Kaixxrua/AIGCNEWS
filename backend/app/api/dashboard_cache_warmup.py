from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

from starlette.requests import Request

from backend.app.api.dependencies import get_github_hot_board_reader
from backend.app.api.routes_dashboard import (
    get_dashboard_summary_static,
    get_snapshot_dates,
    get_top_list,
)
from backend.app.repositories.application_repository_factory import (
    ApplicationRepositories,
)

logger = logging.getLogger(__name__)

# 与前端首屏请求逐字节对齐的预热组合（cache key 只含
# limit/source/date/hours/days_back 白名单参数，period 不进 key）：
# - useDashboardData: summary-static + top(普通源 limit=10，X limit=500)。
# - snapshot-dates(limit=90) 与最近 7 个有数据的历史榜日，显式传 date。
# 默认请求允许回溯最近快照，不能与显式日期请求共用缓存。
# key 不一致 = 预热写入的缓存无人命中，因此参数必须与前端保持同源维护。
_DASHBOARD_TAB_SOURCES = ("github", "arxiv", "news", "producthunt", "hackernews", "x")
_HISTORY_DATES = 7
_AVAILABILITY_LIMIT = 90

_CST = timezone(timedelta(hours=8))


def _stub_request(path: str, query_string: str, *, refresh: bool = False) -> Request:
    """构造仅供 cache key_builder 与端点内 request 读取的最小 Request。

    只暴露 method=GET / query_params / url.path / app.state.redis：
    - method 必须是 GET：fastapi-cache decorator 对非 GET 判为不可缓存，
      会直接跳过写缓存（_uncacheable）；
    - 访客计数仓储由 warmups kwargs 显式传入（直调无 DI），stub 的
      redis=None 不参与访客统计；
    - pdf_media_url 的 origin 由 public_base_url() 仅取 PUBLIC_BASE_URL 配置，
      不读取请求头，stub 不会把内网地址写进缓存。
    """
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "server": ("127.0.0.1", 8000),
        "path": path,
        "raw_path": path.encode("ascii"),
        "query_string": query_string.encode("ascii"),
        "root_path": "",
        "headers": [(b"cache-control", b"no-cache")] if refresh else [],
        "client": ("127.0.0.1", 0),
        "app": SimpleNamespace(state=SimpleNamespace(redis=None)),
    }
    return Request(scope)


async def warm_dashboard_cache(
    repositories: ApplicationRepositories, *, refresh: bool = False,
) -> None:
    """采集完成后重建 dashboard 热缓存，替代「删完 key 等用户撞 ~3s 冷查询」。

    直接调用带 @cache 装饰器的静态端点函数：cache key 与真实 HTTP 请求同源生成，
    不存在手工拼 key 的漂移风险。无 request 形参的端点经装饰器注入位
    `__fastapi_cache_request` 传入 stub Request，与 FastAPI 运行时一致。

    单个端点失败仅记日志，不影响其余端点与采集主流程；整体调用方
    （orchestrator）本就将缓存维护视为非致命路径。
    """
    github_hot = get_github_hot_board_reader()
    semaphore = asyncio.Semaphore(2)

    async def warm(name: str, endpoint: Any, kwargs: dict[str, Any]) -> Any:
        async with semaphore:
            try:
                result = await endpoint(**kwargs)
                logger.info("[Warmup] dashboard %s 缓存已预热。", name)
                return result
            except Exception as exc:  # noqa: BLE001 - 预热失败不应中断采集主流程
                logger.warning("[Warmup] dashboard %s 预热失败（非致命）: %s", name, exc)
                return None

    def top_kwargs(source: str, date: str | None = None) -> dict[str, Any]:
        limit = 500 if source == "x" else 10
        query = f"limit={limit}&source={source}&period=daily"
        if date:
            query += f"&date={date}"
        return {
            "request": _stub_request("/api/dashboard/top", query, refresh=refresh),
            "limit": limit, "source": source, "date": date,
            "rank_snapshots": repositories.rank_snapshots, "github_hot": github_hot,
        }

    warmups: list[tuple[str, Any, dict[str, Any]]] = [
        (
            "summary-static",
            get_dashboard_summary_static,
            {
                "date": None,
                "rank_snapshots": repositories.rank_snapshots,
                "github_hot": github_hot,
                "__fastapi_cache_request": _stub_request(
                    "/api/dashboard/summary-static", "period=daily", refresh=refresh,
                ),
            },
        ),
    ]
    for source in _DASHBOARD_TAB_SOURCES:
        warmups.append(
            (
                f"top[{source}]",
                get_top_list,
                top_kwargs(source),
            )
        )
    # 首屏优先；历史预热共用并发上限，避免重启或采集后集中压数据库。
    await asyncio.gather(*(warm(*entry) for entry in warmups))

    async def warm_history(source: str) -> None:
        availability = await warm(f"snapshot-dates[{source}]", get_snapshot_dates, {
            "limit": _AVAILABILITY_LIMIT, "source": source,
            "rank_snapshots": repositories.rank_snapshots, "github_hot": github_hot,
            "__fastapi_cache_request": _stub_request(
                "/api/dashboard/snapshot-dates",
                f"limit={_AVAILABILITY_LIMIT}&source={source}&period=daily", refresh=refresh,
            ),
        })
        today = datetime.now(_CST).date().isoformat()
        dates = sorted({date for date in (availability or {}).get("dates", []) if date < today}, reverse=True)
        for date in dates[:_HISTORY_DATES]:
            await warm(f"top[{source},{date}]", get_top_list, top_kwargs(source, date))

    await asyncio.gather(*(warm_history(source) for source in _DASHBOARD_TAB_SOURCES))


def _next_warmup_delay(now: datetime) -> float:
    midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    # 60s 榜单缓存提前刷新；跨日后立即建立新日期的默认缓存键。
    return min(45.0, (midnight - now).total_seconds() + 1.0)


async def maintain_dashboard_cache(repositories: ApplicationRepositories) -> None:
    """启动即预热，此后提前重建并替换缓存；重算期间保留现有可用值。"""
    while True:
        started = asyncio.get_running_loop().time()
        try:
            await warm_dashboard_cache(repositories, refresh=True)
        except Exception as exc:  # noqa: BLE001 - 预热维护不能中断服务
            logger.warning("[Warmup] dashboard 维护失败（非致命）: %s", exc)
        elapsed = asyncio.get_running_loop().time() - started
        await asyncio.sleep(max(1.0, min(45.0 - elapsed, _next_warmup_delay(datetime.now(_CST)))))
