from __future__ import annotations

"""Arxiv 数据源：Hugging Face Daily Papers HTML + arXiv XML API 双轨策略（v3）。

策略：
  1. 请求 https://huggingface.co/papers/date/{YYYY-MM-DD} 获取当日页面
  2. 从 HTML 中提取 Arxiv ID 与 upvotes（热度），按热度降序排列取 Top N
  3. **并发** 请求 https://huggingface.co/papers/{id} 抓取 HF 详情页（标题/摘要/作者等）
  4. 用 arXiv 官方 XML API 补充/校正元数据（摘要更完整、发布日期更准确）
  5. source='arxiv'，source_channel='huggingface_daily_html'
  6. PDF 内容由后台 ArxivPdfDownloader 异步落盘，不在此阶段下载

v3 变更：
  - 新增 Step 4：arXiv XML API 补全元数据（摘要 / 作者 / 日期）
  - pdf_url 统一为 https://arxiv.org/pdf/{arxiv_id}（落盘下载时使用）
"""

import asyncio
import logging
import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# ── HuggingFace 基础 URL（支持镜像） ─────────────────────────────────────────

_HF_DEFAULT_BASE = "https://huggingface.co"


def _get_hf_base() -> str:
    """读取 HF_ENDPOINT 配置（优先 settings，回退环境变量），返回 base URL。"""
    base = ""
    try:
        from backend.app.core.config import settings

        base = (settings.hf_endpoint or "").strip().rstrip("/")
    except Exception:
        pass
    if not base:
        base = os.getenv("HF_ENDPOINT", "").strip().rstrip("/")
    if not base:
        base = _HF_DEFAULT_BASE
    return base


def _hf_papers_daily_url(date: str) -> str:
    return f"{_get_hf_base()}/papers/date/{date}"


def _hf_papers_weekly_url(week: str) -> str:
    return f"{_get_hf_base()}/papers/week/{week}"


def _hf_papers_monthly_url(month: str) -> str:
    return f"{_get_hf_base()}/papers/month/{month}"


def _hf_papers_base() -> str:
    return f"{_get_hf_base()}/papers"


# 匹配 Arxiv ID，支持格式：2312.12345 / 2312.12345v2
_ARXIV_ID_RE = re.compile(r"(\d{4}\.\d{4,5}(?:v\d+)?)")

# 并发控制
_SEMAPHORE_LIMIT = 10


def _get_headers() -> Dict[str, str]:
    """构造请求 Headers，注入 HuggingFace Token（如有）。"""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
    }
    token = ""
    try:
        from backend.app.core.config import settings

        token = settings.huggingface_token
    except Exception:
        pass
    if not token:
        token = os.getenv("HUGGINGFACE_TOKEN", "")
    if token:
        headers["Authorization"] = f"Bearer {token}"
        logger.debug("[Arxiv][HF] 已注入 HuggingFace Token")
    return headers


# ── 工具函数 ──────────────────────────────────────────────────────────────────


def _extract_arxiv_id(text: str) -> Optional[str]:
    """从 HF papers 链接或任意文本中提取 Arxiv ID。"""
    m = _ARXIV_ID_RE.search(text or "")
    return m.group(1) if m else None


def _normalize_arxiv_id(arxiv_id: str) -> str:
    """去掉版本号，保持 ID 干净（如 2312.12345）。"""
    return arxiv_id.split("v")[0]


# ── Step 1: 从日期页提取 ID 列表 + upvotes ────────────────────────────────────


def _parse_upvotes_from_card(card: Any) -> Optional[int]:
    """从单个论文卡片中解析点赞数。"""
    candidates: List[Tuple[int, int]] = []
    for tag in card.find_all(["span", "div", "p"]):
        text = " ".join(tag.stripped_strings)
        if not text or not re.fullmatch(r"\d+", text):
            continue
        try:
            score = int(text)
        except ValueError:
            continue
        class_tokens = tag.get("class", [])
        class_str = " ".join(class_tokens) if class_tokens else ""
        weight = 0
        if "leading-none" in class_str:
            weight += 3
        if "font-bold" in class_str or "font-semibold" in class_str:
            weight += 2
        if "text-sm" in class_str:
            weight += 1
        candidates.append((weight, score))

    if candidates:
        return max(candidates)[1]
    return None


def _extract_daily_ids_from_html(html: str, limit: int) -> List[Tuple[str, int]]:
    """从 HF 榜单页面 HTML 提取 (arxiv_id, upvotes)，按热度降序。"""
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.find_all("article")
    if not cards:
        cards = soup.find_all("h3")

    id_to_upvotes: Dict[str, int] = {}

    for card in cards:
        link = card.find("a", href=re.compile(r"/papers/"))
        if not link or not link.get("href"):
            continue
        arxiv_id = _extract_arxiv_id(link.get("href"))
        if not arxiv_id:
            continue
        clean_id = _normalize_arxiv_id(arxiv_id)
        upvotes = _parse_upvotes_from_card(card) or 0
        if clean_id not in id_to_upvotes or upvotes > id_to_upvotes[clean_id]:
            id_to_upvotes[clean_id] = upvotes

    pairs = sorted(id_to_upvotes.items(), key=lambda x: x[1], reverse=True)
    top_n = min(limit, 20)
    return pairs[:top_n]


def _get_period_url(period: str, target_date: Optional[datetime] = None) -> str:
    dt = target_date or datetime.utcnow()
    period = (period or "daily").lower().strip()

    if period == "weekly":
        iso_year, iso_week, _ = dt.isocalendar()
        return _hf_papers_weekly_url(f"{iso_year}-W{iso_week:02d}")
    if period == "monthly":
        return _hf_papers_monthly_url(dt.strftime("%Y-%m"))
    return _hf_papers_daily_url(dt.date().isoformat())


async def _fetch_hf_listing_html(
    period: str = "daily",
    limit: int = 20,
    target_date: Optional[datetime] = None,
) -> Tuple[List[str], Dict[str, int]]:
    """异步抓取 HF 榜单 HTML，返回 (arxiv_ids, id->upvotes)。"""
    period = (period or "daily").lower().strip()
    headers = _get_headers()

    if period == "daily" and target_date is None:
        base_date = datetime.utcnow().date()
        candidates = [
            _hf_papers_daily_url(
                base_date.fromordinal(base_date.toordinal() - day_offset).isoformat()
            )
            for day_offset in range(0, 2)
        ]
    else:
        candidates = [_get_period_url(period, target_date=target_date)]

    async with httpx.AsyncClient(
        headers=headers, timeout=15, follow_redirects=True
    ) as client:
        for url in candidates:
            try:
                resp = await client.get(url)
                resp.raise_for_status()
                pairs = _extract_daily_ids_from_html(resp.text, limit=limit)
                if pairs:
                    arxiv_ids = [arxiv_id for arxiv_id, _ in pairs]
                    id_to_upvotes = {arxiv_id: upvotes for arxiv_id, upvotes in pairs}
                    logger.info(
                        "[Arxiv][HF] %s 榜单解析完成，获得 %d 个 Arxiv ID。",
                        period,
                        len(arxiv_ids),
                    )
                    return arxiv_ids, id_to_upvotes
                logger.warning("[Arxiv][HF] %s 榜单解析无结果: %s", period, url)
            except Exception as exc:
                logger.error("[Arxiv][HF] %s 榜单抓取失败 %s: %s", period, url, exc)

    return [], {}


# ── Step 2: 并发抓取 HF 论文详情页 ──────────────────────────────────────────


def _parse_paper_detail(html: str, arxiv_id: str) -> Optional[Dict[str, Any]]:
    """从 HF 论文详情页 HTML 解析元数据。"""
    soup = BeautifulSoup(html, "html.parser")

    # ── 标题 ──
    h1 = soup.find("h1")
    title = h1.get_text(strip=True) if h1 else arxiv_id

    # ── 摘要：取所有 <p> 中最长的（通常是完整 Abstract） ──
    paragraphs = [
        p.get_text(strip=True)
        for p in soup.find_all("p")
        if len(p.get_text(strip=True)) > 80
    ]
    _noise = ("librarian bot", "semantic scholar", "thanks to", "code:", "page:")
    paragraphs = [p for p in paragraphs if not any(n in p.lower() for n in _noise)]
    abstract = max(paragraphs, key=len) if paragraphs else ""

    # ── 作者：<span class="author ..."> ──
    author_spans = soup.find_all(
        "span", class_=lambda c: c and "author" in " ".join(c).lower()
    )
    authors = [s.get_text(strip=True).rstrip(",").strip() for s in author_spans[:5]]

    # ── 发布日期：<time datetime="..."> ──
    time_el = soup.find("time", attrs={"datetime": True})
    published_date = ""
    if time_el:
        try:
            dt = datetime.fromisoformat(time_el["datetime"].replace("Z", "+00:00"))
            published_date = dt.isoformat()
        except Exception:
            published_date = time_el.get("datetime", "")

    # ── URL ──
    hf_url = f"{_hf_papers_base()}/{arxiv_id}"
    original_arxiv_url = f"https://arxiv.org/abs/{arxiv_id}"
    pdf_url = f"https://arxiv.org/pdf/{arxiv_id}"

    return {
        "title": title,
        "abstract": abstract,
        "published_date": published_date,
        "url": hf_url,
        "pdf_url": pdf_url,
        "source": "arxiv",
        "source_channel": "huggingface_daily_html",
        "channel": "huggingface_daily_html",
        "original_arxiv_url": original_arxiv_url,
        "arxiv_id": arxiv_id,
        "authors": authors,
        "claps": None,
        "score": None,
    }


async def _fetch_single_detail(
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
    arxiv_id: str,
    rank: int,
    upvotes: int,
    source_channel: str,
) -> Optional[Dict[str, Any]]:
    """异步抓取单篇论文详情页（受 semaphore 并发控制）。"""
    url = f"{_hf_papers_base()}/{arxiv_id}"
    async with semaphore:
        try:
            resp = await client.get(url)
            resp.raise_for_status()
            doc = _parse_paper_detail(resp.text, arxiv_id)
            if doc:
                doc["claps"] = upvotes
                doc["score"] = upvotes
                doc["raw_score"] = upvotes
                doc["source_channel"] = source_channel
                doc["channel"] = source_channel
                doc["rank_in_period"] = rank
                logger.debug(
                    "[Arxiv][HF] 详情抓取成功: %s (rank=%d, claps=%s)",
                    arxiv_id,
                    rank,
                    upvotes,
                )
                return doc
        except Exception as exc:
            logger.warning("[Arxiv][HF] 详情抓取失败 %s: %s", arxiv_id, exc)
    return None


async def _fetch_paper_details_async(
    arxiv_ids: List[str],
    id_to_upvotes: Dict[str, int],
    source_channel: str = "huggingface_daily_html",
) -> List[Dict[str, Any]]:
    """并发请求所有论文详情页（asyncio.gather + Semaphore）。

    相比旧版逐个请求 + 1s sleep，20 篇论文从 20s+ 降至 1-2s。
    """
    semaphore = asyncio.Semaphore(_SEMAPHORE_LIMIT)
    headers = _get_headers()

    async with httpx.AsyncClient(
        headers=headers, timeout=15, follow_redirects=True
    ) as client:
        tasks = [
            _fetch_single_detail(
                client=client,
                semaphore=semaphore,
                arxiv_id=arxiv_id,
                rank=rank,
                upvotes=id_to_upvotes.get(arxiv_id, 0),
                source_channel=source_channel,
            )
            for rank, arxiv_id in enumerate(arxiv_ids, start=1)
        ]
        results = await asyncio.gather(*tasks)

    # 过滤 None，保持原始排名顺序
    docs = [doc for doc in results if doc is not None]
    return docs


# ── 核心异步函数 ──────────────────────────────────────────────────────────────


async def _enrich_with_arxiv_api(
    docs: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """用 arXiv XML API 补全/校正元数据（摘要更完整、发布日期更准确）。

    HF 详情页有时摘要被截断，arXiv API 返回完整 abstract。
    本函数在独立线程中同步调用 API，不阻塞事件循环。
    """
    arxiv_ids = [d["arxiv_id"] for d in docs if d.get("arxiv_id")]
    if not arxiv_ids:
        return docs

    try:
        from backend.app.services.ingestion.arxiv_pdf_downloader import (
            _fetch_arxiv_metadata_by_ids,
        )

        api_papers = await asyncio.to_thread(_fetch_arxiv_metadata_by_ids, arxiv_ids)
        api_map: Dict[str, Dict[str, Any]] = {
            p["arxiv_id"]: p for p in api_papers if p.get("arxiv_id")
        }

        for doc in docs:
            arxiv_id = doc.get("arxiv_id", "")
            api_data = api_map.get(arxiv_id)
            if not api_data:
                continue
            # 用 API 返回的更完整摘要覆盖 HF 解析结果（API 更权威）
            if api_data.get("abstract") and len(api_data["abstract"]) > len(
                doc.get("abstract", "")
            ):
                doc["abstract"] = api_data["abstract"]
            # 补全作者（HF 详情页可能解析失败）
            if api_data.get("authors") and not doc.get("authors"):
                doc["authors"] = api_data["authors"]
            # 补全发布日期
            if api_data.get("published_date") and not doc.get("published_date"):
                doc["published_date"] = api_data["published_date"]

        logger.info(
            "[Arxiv][API] arXiv XML API 元数据补全完成，%d/%d 篇命中。",
            len(api_map),
            len(arxiv_ids),
        )
    except Exception as exc:
        logger.warning(
            "[Arxiv][API] arXiv XML API 补全失败（非致命，使用 HF 数据）: %s", exc
        )

    return docs


async def fetch_latest_papers_async(
    limit: int = 20,
    period: str = "daily",
    target_date: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """异步版：通过 HuggingFace Papers HTML 获取指定周期论文元数据，
    并用 arXiv XML API 补全/校正摘要和发布日期。
    """
    period = (period or "daily").lower().strip()
    target_dt = None
    if target_date:
        target_dt = datetime.fromisoformat(target_date)

    source_channel = f"huggingface_{period}_html"
    arxiv_ids, id_to_upvotes = await _fetch_hf_listing_html(
        period=period,
        limit=limit,
        target_date=target_dt,
    )
    if not arxiv_ids:
        raise RuntimeError(f"[Arxiv][HF] {period} 榜单抓取失败或解析为空，已终止采集。")

    logger.info(
        "[Arxiv][HF] 准备并发抓取 %d 篇论文详情（period=%s，Semaphore=%d）...",
        len(arxiv_ids),
        period,
        _SEMAPHORE_LIMIT,
    )

    docs = await _fetch_paper_details_async(
        arxiv_ids,
        id_to_upvotes,
        source_channel=source_channel,
    )
    if not docs:
        raise RuntimeError(
            f"[Arxiv][HF] {period} 榜单论文详情全部抓取失败，已终止采集。"
        )

    # ── Step 4：arXiv XML API 补全元数据 ──
    docs = await _enrich_with_arxiv_api(docs)

    logger.info(
        "[Arxiv][HF] 成功构造 %d/%d 篇 HF %s Papers 文档（HF+API 双轨）。",
        len(docs),
        len(arxiv_ids),
        period,
    )
    return docs


# ── 同步兼容包装器（供 crawlers 调用） ────────────────────────────────────────


def fetch_latest_papers(
    limit: int = 20,
    period: str = "daily",
    target_date: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """同步包装器：自动检测是否有运行中的事件循环，选择合适的调用方式。

    - 如果在已有 asyncio 事件循环中（如 FastAPI 路由）：创建新线程运行
    - 如果没有事件循环：直接 asyncio.run()
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        # 在已有事件循环中（如 FastAPI），使用线程池避免阻塞
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(
                asyncio.run,
                fetch_latest_papers_async(
                    limit=limit, period=period, target_date=target_date
                ),
            )
            return future.result(timeout=120)
    else:
        return asyncio.run(
            fetch_latest_papers_async(
                limit=limit, period=period, target_date=target_date
            )
        )
