from __future__ import annotations

"""GitHub Trending 数据源（async 极速版 — 直接爬 github.com/trending）

策略：
  1. 请求 https://github.com/trending（日榜）
     https://github.com/trending?since=weekly（周榜）
     https://github.com/trending?since=monthly（月榜）
  2. 解析 HTML，提取仓库列表，**按网页原始顺序**作为 rank_in_period（第1名=排名最高）
  3. 每个周期独立取 Top-N，source_channel 分别为：
     github_trending_daily / github_trending_weekly / github_trending_monthly
  4. 注入 GITHUB_TOKEN 提高 API 限额，使用 httpx.AsyncClient 加速

性能优化（v2）：
  - 使用 httpx.AsyncClient 替代同步 httpx.Client
  - 注入 GITHUB_TOKEN（有 Token 每小时 5000 次 vs 无 Token 60 次）
  - fetch_github_trending_all_periods 使用 asyncio.gather 并发三周期

返回字段（兼容 pipeline._to_documents）：
  - title:              full_name（如 "owner/repo"）
  - abstract:           description
  - url:                https://github.com/{full_name}
  - source:             "github"
  - source_channel:     "github_trending_{period}"
  - period_star_growth: GitHub 页面报告的对应周期 Stars 增长
  - raw_score:          period_star_growth（仅用于当前周期榜单）
  - stars:              total stars
  - language:           主语言
  - rank_in_period:     在榜单中的排名（1=第一名）
  - published_date:     今日日期（采集日）
"""

import asyncio
import logging
import re
from datetime import date
from typing import Any, Dict, List

import httpx
from bs4 import BeautifulSoup

from backend.app.core.config import settings

logger = logging.getLogger(__name__)

_BASE_URL = "https://github.com/trending"

_PERIOD_PARAMS = {
    "daily": "",  # 默认就是 daily（Today）
    "weekly": "weekly",
    "monthly": "monthly",
}

_CHANNEL_MAP = {
    "daily": "github_trending_daily",
    "weekly": "github_trending_weekly",
    "monthly": "github_trending_monthly",
}

_PERIOD_GROWTH_SUFFIXES = {
    "daily": "today",
    "weekly": "this week",
    "monthly": "this month",
}


def _get_headers() -> Dict[str, str]:
    """构造请求 Headers，注入 GitHub Token（如有）。"""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    token = settings.github_token.strip()
    if token:
        headers["Authorization"] = f"token {token}"
        logger.debug("[GitHub Trending] 已注入 GitHub Token")
    return headers


def _parse_int(text: str) -> int:
    """从字符串提取数字，去掉逗号和空格。"""
    clean = re.sub(r"[^\d]", "", text or "")
    return int(clean) if clean else 0


def parse_github_trending_html(
    html: str,
    *,
    period: str = "daily",
    limit: int = 25,
) -> List[Dict[str, Any]]:
    """解析 GitHub Trending 页面并保留对应周期的增长语义。"""
    normalized_period = (period or "daily").lower().strip()
    if normalized_period not in _PERIOD_PARAMS:
        raise ValueError(f"Unsupported period: {period}")
    expected_growth_suffix = _PERIOD_GROWTH_SUFFIXES[normalized_period]
    effective_limit = max(0, int(limit or 0))
    if effective_limit == 0:
        return []
    soup = BeautifulSoup(html, "html.parser")

    # 每个仓库是一个 <article class="Box-row">
    articles = soup.find_all("article", class_=re.compile(r"Box-row"))
    if not articles:
        # 备用：尝试更宽泛的选择器
        articles = soup.find_all("article")

    repos: List[Dict[str, Any]] = []

    for article in articles:
        # ── 仓库名（full_name） ──────────────────────────────────
        h2 = article.find("h2")
        if not h2:
            continue
        link = h2.find("a")
        if not link or not link.get("href"):
            continue
        href = link["href"].strip("/")  # "owner/repo"
        full_name = href
        if full_name.count("/") != 1:
            continue

        # ── 描述 ────────────────────────────────────────────────
        desc_tag = article.find("p")
        description = desc_tag.get_text(strip=True) if desc_tag else ""

        # ── 主语言 ──────────────────────────────────────────────
        lang_tag = article.find("span", attrs={"itemprop": "programmingLanguage"})
        language = lang_tag.get_text(strip=True) if lang_tag else ""

        # ── 总 Stars ────────────────────────────────────────────
        stars_tag = article.find("a", href=re.compile(r"/stargazers$"))
        total_stars = _parse_int(stars_tag.get_text(strip=True)) if stars_tag else 0

        # ── 对应周期新增 Stars ──────────────────────────────────
        period_star_growth: int | None = None
        for span in article.find_all("span"):
            text = " ".join(span.get_text(" ", strip=True).lower().split())
            if "stars" in text and expected_growth_suffix in text:
                period_star_growth = _parse_int(text)
                break

        rank = len(repos) + 1
        repos.append(
            {
                "repo_id": full_name,
                "full_name": full_name,
                "title": full_name,
                "description": description,
                "abstract": description,
                "summary": description,
                "url": f"https://github.com/{full_name}",
                "pdf_url": "",
                "language": language,
                "stars": total_stars,
                "period": normalized_period,
                "period_star_growth": period_star_growth,
                "rank": rank,
                "rank_in_period": rank,
                "raw_score": float(period_star_growth or 0),
                "score": float(period_star_growth or 0),
            }
        )
        if len(repos) >= effective_limit:
            break

    return repos


def _parse_trending_html(html: str) -> List[Dict[str, Any]]:
    """兼容旧调用：按日榜语义解析 Trending 页面。"""
    return parse_github_trending_html(html, period="daily")


async def fetch_github_trending_async(
    period: str = "daily",
    limit: int = 25,
    language: str = "",
) -> List[Dict[str, Any]]:
    """异步爬取 GitHub Trending 指定周期榜单。

    Args:
        period:   "daily" / "weekly" / "monthly"
        limit:    最多返回条数（网页通常返回 25 条）
        language: 可选过滤语言（如 "python"）

    Returns:
        按网页原始顺序排列的仓库 dict 列表，每条含 rank_in_period 字段。
    """
    period = (period or "daily").lower().strip()
    since = _PERIOD_PARAMS.get(period, "")
    channel = _CHANNEL_MAP.get(period, "github_trending_daily")
    today = date.today().isoformat()
    headers = _get_headers()

    url = _BASE_URL
    params: Dict[str, str] = {}
    if since:
        params["since"] = since
    if language:
        params["spoken_language_code"] = ""
        url = f"{_BASE_URL}/{language.lower()}"

    try:
        async with httpx.AsyncClient(
            timeout=20,
            follow_redirects=True,
            headers=headers,
        ) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            html = resp.text
    except Exception as exc:
        logger.error("[GitHub Trending] %s 榜抓取失败: %s", period, exc)
        return []

    repos = parse_github_trending_html(html, period=period, limit=limit)

    if not repos:
        logger.warning(
            "[GitHub Trending] %s 榜解析结果为空（HTML 可能结构变化）。", period
        )
        return []

    result: List[Dict[str, Any]] = []
    for rank, repo in enumerate(repos, start=1):
        repo["source"] = "github"
        repo["source_channel"] = channel
        repo["channel"] = channel
        repo["period"] = period
        repo["rank"] = rank
        repo["rank_in_period"] = rank
        repo["published_date"] = today
        repo["created_at"] = today
        repo["tags"] = [repo.get("language") or "GitHub", period, "trending"]
        result.append(repo)

    logger.info(
        "[GitHub Trending] %s 榜解析完成，共 %d 条（前 %d 名）。",
        period,
        len(result),
        len(result),
    )
    return result


async def fetch_github_trending_all_periods_async(
    limit: int = 25,
) -> Dict[str, List[Dict[str, Any]]]:
    """并发抓取三个周期（daily/weekly/monthly）的 GitHub Trending。

    使用 asyncio.gather 并发三个请求，总耗时 ≈ 单次请求耗时（而非 3× 串行）。
    """
    daily, weekly, monthly = await asyncio.gather(
        fetch_github_trending_async(period="daily", limit=limit),
        fetch_github_trending_async(period="weekly", limit=limit),
        fetch_github_trending_async(period="monthly", limit=limit),
    )
    return {"daily": daily, "weekly": weekly, "monthly": monthly}


# ── 同步兼容包装器（供 crawlers 调用） ────────────────────────────────────────


def fetch_github_trending(
    period: str = "daily",
    limit: int = 25,
    language: str = "",
) -> List[Dict[str, Any]]:
    """同步包装器：自动检测事件循环，选择合适的调用方式。"""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(
                asyncio.run,
                fetch_github_trending_async(
                    period=period, limit=limit, language=language
                ),
            )
            return future.result(timeout=60)
    else:
        return asyncio.run(
            fetch_github_trending_async(period=period, limit=limit, language=language)
        )


def fetch_github_trending_all_periods(
    limit: int = 25,
    delay: float = 1.5,
) -> Dict[str, List[Dict[str, Any]]]:
    """同步包装器：并发抓取三周期（delay 参数保留兼容但不再使用）。"""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(
                asyncio.run,
                fetch_github_trending_all_periods_async(limit=limit),
            )
            return future.result(timeout=90)
    else:
        return asyncio.run(fetch_github_trending_all_periods_async(limit=limit))
