from __future__ import annotations

"""站点访问的平台维度纯策略：User-Agent 归类 + 窗口聚合响应组装。

口径说明：
- 归类只取 UA 小写子串，不引入 UA 解析依赖；顺序即语义，调整顺序必须同步测试。
- 自动化访问必须最先判：Googlebot 智能手机版带 `Linux; Android`，Applebot 带
  `iPhone`，先判平台会把爬虫算成真人访问。无头浏览器（HeadlessChrome 等）每个
  全新上下文都会生成新访客 ID，本机截图脚本曾一天灌进数百次，同样归入 bot。
- iOS 必须先于 macOS：iPhone/iPad 的 UA 带 `like Mac OS X` 字样，顺序颠倒会把
  iOS 流量错划进 macos。
- iPadOS 13+ 桌面模式 UA 伪装成 `Macintosh; Intel Mac OS X 10_15`，纯 UA 无法
  区分，计入 macos（面板文案已向用户注明该限制）。
- android 必须先于 linux：Android UA 同样带 `Linux` 字样。
- windows phone 落入 windows 桶（份额可忽略）；空 UA、ChromeOS、BSD、HarmonyOS
  NEXT 等其余一律 other。
- 平台桶值域由本模块与 site_visit_repository.PLATFORM_BUCKETS 约束，DB 无 CHECK。
"""

import re
from datetime import date, timedelta
from typing import Iterable, TypedDict

from backend.app.repositories.site_visit_repository import (
    AUTOMATED_PLATFORM,
    DEFAULT_PLATFORM,
    PLATFORM_BUCKETS,
    PlatformVisits,
)

#: 读端点合法窗口枚举（Query pattern 与之保持一致）：today/7d/30d 为含今天的自然日数。
VISIT_STATS_WINDOWS: tuple[str, ...] = ("today", "7d", "30d", "all")

_WINDOW_DAY_SPAN: dict[str, int] = {"today": 1, "7d": 7, "30d": 30}


#: 无头浏览器、测速/审计工具与自动化驱动的 UA 子串。
_AUTOMATION_MARKERS: tuple[str, ...] = (
    "headless",
    "phantomjs",
    "puppeteer",
    "playwright",
    "selenium",
    "webdriver",
    "lighthouse",
    "pagespeed",
    "gtmetrix",
    "facebookexternalhit",
    "meta-externalagent",
    "google-inspectiontool",
    "google-pagerenderer",
    "slurp",
    # 爬虫惯例在 UA 里附 `+http(s)://…` 说明页，真实浏览器不会出现
    "+http",
)

#: 爬虫自报名：`…bot` / `…spider` / `…crawler` 后紧跟 `/`、`;`、`)`、`-` 或结尾。
#: 限定后缀是为了放过 CUBOT 这类手机型号（`CUBOT_X19`、`CUBOT X30`）。
_CRAWLER_TOKEN = re.compile(r"(?:bot|spider|crawler)(?=[/;)\-]|$)")

#: 脚本 HTTP 客户端把自己的名字放在 UA 开头。
_SCRIPT_CLIENT_PREFIXES: tuple[str, ...] = (
    "curl/",
    "wget/",
    "python-requests/",
    "python-urllib/",
    "python-httpx/",
    "aiohttp/",
    "go-http-client/",
    "java/",
    "okhttp/",
    "node",  # undici 默认 UA 即 `node`，node-fetch 为 `node-fetch/…`
    "undici",
    "axios/",
    "scrapy/",
    "libwww-perl/",
    "httpie/",
    "postmanruntime/",
    "apache-httpclient/",
)


def is_automated_user_agent(user_agent: str | None) -> bool:
    """爬虫、无头浏览器、脚本客户端返回 True；空 UA 无从判断，按真人处理。"""
    if not user_agent:
        return False
    ua = user_agent.casefold().strip()
    if ua.startswith(_SCRIPT_CLIENT_PREFIXES):
        return True
    if any(marker in ua for marker in _AUTOMATION_MARKERS):
        return True
    return _CRAWLER_TOKEN.search(ua) is not None


def classify_platform(user_agent: str | None) -> str:
    """把 User-Agent 归入平台桶；自动化访问归 bot，空/无法识别一律 other。"""
    if not user_agent:
        return DEFAULT_PLATFORM
    if is_automated_user_agent(user_agent):
        return AUTOMATED_PLATFORM
    ua = user_agent.casefold()
    if "iphone" in ua or "ipad" in ua or "ipod" in ua:
        return "ios"
    if "android" in ua:
        return "android"
    if "windows" in ua:
        return "windows"
    if "mac os x" in ua or "macintosh" in ua:
        return "macos"
    if "linux" in ua:
        return "linux"
    return DEFAULT_PLATFORM


def window_start_date(window: str, today: date) -> date | None:
    """窗口下界（含）：today→当天；7d/30d→today-(N-1)；all→None（无下界）。"""
    span = _WINDOW_DAY_SPAN.get(window)
    if span is None:
        return None
    return today - timedelta(days=span - 1)


class PlatformShareEntry(TypedDict):
    platform: str
    visits: int
    share: float


class PlatformBreakdownResponse(TypedDict):
    window: str
    start_date: str | None
    end_date: str
    total_visits: int
    platforms: list[PlatformShareEntry]
    automated_visits: int


def build_platform_breakdown_response(
    rows: Iterable[PlatformVisits],
    window: str,
    today: date,
) -> PlatformBreakdownResponse:
    """把仓储聚合行组装为读端点响应：固定桶序、补零值桶、share 一位小数。

    bot 桶不进 platforms 与 total_visits（与站点访问量口径一致），单独汇总为
    automated_visits。其余未识别桶（历史脏数据等）折叠进 other，保证 platforms
    桶集合恒为 PLATFORM_BUCKETS。share 仅为信息性字段：一位小数直接相加可能漂移
    ±0.1，前端展示百分比以原始 visits 本地大余数法重算为准。
    """
    visits_by_bucket = dict.fromkeys(PLATFORM_BUCKETS, 0)
    automated_visits = 0
    for row in rows:
        visits = max(int(row.visits), 0)
        if row.platform == AUTOMATED_PLATFORM:
            automated_visits += visits
            continue
        bucket = row.platform if row.platform in visits_by_bucket else DEFAULT_PLATFORM
        visits_by_bucket[bucket] += visits

    total = sum(visits_by_bucket.values())
    start = window_start_date(window, today)
    return {
        "window": window,
        "start_date": start.isoformat() if start else None,
        "end_date": today.isoformat(),
        "total_visits": total,
        "platforms": [
            {
                "platform": bucket,
                "visits": visits,
                "share": round(visits * 100.0 / total, 1) if total else 0.0,
            }
            for bucket, visits in visits_by_bucket.items()
        ],
        "automated_visits": automated_visits,
    }
