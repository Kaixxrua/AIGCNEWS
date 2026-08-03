from __future__ import annotations

"""内容丰富模块（Content Enricher）

在 Top-N 筛选完成后、入库前，为各数据源补充完整正文：

  - arxiv    : 【快速路径】先用摘要入 RAG（paper["full_text"] = abstract），
               标记 pdf_pending=True，后续由 enrich_arxiv_pdf_full() 补充 PDF 全文。
               PDF URL 格式: https://arxiv.org/pdf/{arxiv_id}
  - huggingface: 直接用描述摘要入 RAG，无需 PDF
  - github   : source_github.py 的 _fetch_readme 已在采集时抓好，
               hot_service 来源需要额外补 README
  - news     : httpx 抓详情页 → readability / BS4 提取正文
  - producthunt: 保持 tagline + description（已足够）
  - hackernews: httpx 抓外链详情页 → BS4 提取正文；
               若为 HN 自带 Ask/Show HN，则用 story_text

所有方法均以 paper dict 为输入/输出，在 paper["full_text"] 写入丰富后的正文，
pipeline._to_documents 会优先使用该字段构建 page_content。

PDF 二阶段策略：
  1. enrich_arxiv()        → 摘要入库，pdf_pending=True
  2. enrich_arxiv_pdf_full() → 后台线程池下载 PDF，更新 full_text
"""

import asyncio
import io
import logging
import re
from typing import Any, Dict, List, Optional

import httpx

from backend.app.services.ingestion import content_enrichment_coordinator
from backend.app.services.ingestion.content_fetch_port import (
    DefaultGitHubReadmeFetcher,
    DefaultPageContentFetcher,
    GitHubReadmeFetcher,
    PageContentFetcher,
    clean_html_text,
)

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    )
}

# 单次网络请求超时（秒）
_HTTP_TIMEOUT = 20
# PDF 最多解析页数（避免超大 PDF 拖慢进程）
_PDF_MAX_PAGES = 50
# 正文最大字符数（防止 Milvus chunk 过多）
_MAX_CONTENT_CHARS = 40_000


# ── 工具函数 ──────────────────────────────────────────────────────────────────


def _clean_html_text(html: str) -> str:
    """从 HTML 提取可读纯文本。"""
    return clean_html_text(html)


async def _fetch_url_text(url: str, timeout: int = _HTTP_TIMEOUT) -> str:
    """抓取 URL 页面并返回纯文本，失败返回空字符串。"""
    fetcher = DefaultPageContentFetcher(headers=_HEADERS, clean_html=_clean_html_text)
    return await fetcher.fetch(url, timeout)


def _fetch_pdf_text(pdf_url: str, timeout: int = 30) -> str:
    """下载 PDF 并用 pypdf 解析前 N 页文本，失败返回空字符串。"""
    if not pdf_url or not pdf_url.startswith("http"):
        return ""
    try:
        import pypdf  # type: ignore
    except ImportError:
        logger.warning("[Enricher] pypdf 未安装，跳过 PDF 解析。pip install pypdf")
        return ""

    try:
        with httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            headers=_HEADERS,
            trust_env=True,
        ) as client:
            resp = client.get(pdf_url)
            resp.raise_for_status()
            ct = resp.headers.get("content-type", "")
            if "pdf" not in ct and not pdf_url.lower().endswith(".pdf"):
                return ""
            pdf_bytes = resp.content

        reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
        pages = reader.pages[:_PDF_MAX_PAGES]
        parts = []
        for page in pages:
            try:
                parts.append(page.extract_text() or "")
            except Exception:
                pass
        text = "\n".join(parts)
        # 折叠多余空白
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        return text
    except Exception as exc:
        logger.debug("[Enricher] PDF 解析失败 %s: %s", pdf_url, exc)
        return ""


async def _fetch_github_readme(full_name: str) -> str:
    """通过共享 GitHub README 抓取器获取清洗后的文本。"""
    return await DefaultGitHubReadmeFetcher().fetch(full_name)


# ── 各源 Enricher ──────────────────────────────────────────────────────────────


def enrich_arxiv(paper: Dict[str, Any]) -> Dict[str, Any]:
    """Arxiv 论文：【快速路径】先用摘要入 RAG。

    第一阶段：直接使用已抓好的摘要 (abstract) 入库，让 RAG 可以立即检索。
    第二阶段：由 pipeline._start_arxiv_pdf_background() 调用
              arxiv_pdf_downloader.download_and_index_arxiv_pdfs() 在后台
              落盘 PDF → PyMuPDF 解析 → 切片写入 Milvus。

    如果本地 PDF 已存在（local_pdf_path），直接读取全文作为 full_text。

    PDF URL 格式: https://arxiv.org/pdf/{arxiv_id}
    """
    arxiv_id = paper.get("arxiv_id", "")
    abstract = paper.get("abstract", "") or paper.get("summary", "")

    # 确保 pdf_url 使用正确格式
    pdf_url = paper.get("pdf_url", "")
    if arxiv_id and not pdf_url:
        pdf_url = f"https://arxiv.org/pdf/{arxiv_id}"
        paper["pdf_url"] = pdf_url
    elif arxiv_id and "arxiv.org" in pdf_url and "/pdf/" not in pdf_url:
        # 修正 /abs/ 路径为 /pdf/
        pdf_url = f"https://arxiv.org/pdf/{arxiv_id}"
        paper["pdf_url"] = pdf_url

    # 如果本地 PDF 已落盘，直接读取全文
    local_pdf_path = paper.get("local_pdf_path", "")
    if local_pdf_path:
        try:
            from backend.app.services.ingestion.arxiv_pdf_downloader import (
                _extract_text_from_local_pdf,
            )

            pdf_text = _extract_text_from_local_pdf(local_pdf_path)
            if pdf_text:
                full_text = (
                    f"Abstract:\n{abstract}\n\nFull Paper:\n{pdf_text}"
                    if abstract
                    else pdf_text
                )
                paper["full_text"] = full_text[:_MAX_CONTENT_CHARS]
                paper["pdf_pending"] = False
                logger.debug(
                    "[Enricher][Arxiv] 本地 PDF 已存在，直接读取: %s (%d chars)",
                    local_pdf_path,
                    len(paper["full_text"]),
                )
                return paper
        except Exception as exc:
            logger.debug("[Enricher][Arxiv] 本地 PDF 读取失败，回退到摘要: %s", exc)

    # 快速路径：使用摘要入库，后台 PDF 下载器会补全
    full_text = abstract or paper.get("title", "")
    paper["full_text"] = full_text[:_MAX_CONTENT_CHARS]
    paper["pdf_pending"] = True  # 标记需要后台补 PDF

    logger.debug(
        "[Enricher][Arxiv] 摘要入库（pdf_pending=True），后台将落盘 PDF: %s",
        arxiv_id or pdf_url,
    )
    return paper


def enrich_arxiv_pdf_full(paper: Dict[str, Any]) -> Dict[str, Any]:
    """Arxiv 论文：【PDF 补全阶段】下载 PDF 解析全文，更新 full_text。

    在摘要已入库后，后台调用此函数补充 PDF 全文。
    调用方需自行将更新后的 full_text 重新写入 Milvus / SQLite。
    """
    arxiv_id = paper.get("arxiv_id", "")
    pdf_url = paper.get("pdf_url", "")
    abstract = paper.get("abstract", "") or paper.get("summary", "")

    # 确保 pdf_url 格式正确
    if arxiv_id and (not pdf_url or "/pdf/" not in pdf_url):
        pdf_url = f"https://arxiv.org/pdf/{arxiv_id}"
        paper["pdf_url"] = pdf_url

    if not pdf_url:
        logger.warning("[Enricher][Arxiv] 无 PDF URL，跳过: %s", arxiv_id)
        paper["pdf_pending"] = False
        return paper

    logger.info("[Enricher][Arxiv] 下载 PDF（补全阶段）: %s", pdf_url)
    pdf_text = _fetch_pdf_text(pdf_url)

    if pdf_text:
        full_text = f"Abstract:\n{abstract}\n\nFull Paper:\n{pdf_text}"
        paper["full_text"] = full_text[:_MAX_CONTENT_CHARS]
        paper["pdf_pending"] = False
        logger.info(
            "[Enricher][Arxiv] PDF 补全成功 %s，full_text %d chars",
            arxiv_id,
            len(paper["full_text"]),
        )
    else:
        logger.warning(
            "[Enricher][Arxiv] PDF 解析失败，保留摘要: %s", arxiv_id or pdf_url
        )
        paper["pdf_pending"] = False  # 即使失败也清除标记，避免反复重试

    return paper


def enrich_huggingface(paper: Dict[str, Any]) -> Dict[str, Any]:
    """HuggingFace 模型：兼容入口，委托非 PDF 内容协调器。"""
    return content_enrichment_coordinator.enrich_huggingface(paper)


async def enrich_github(
    paper: Dict[str, Any],
    readme_fetcher: Optional[GitHubReadmeFetcher] = None,
) -> Dict[str, Any]:
    """GitHub 仓库：兼容入口，保留模块 README 抓取 seam。"""
    return await content_enrichment_coordinator.enrich_github(
        paper,
        readme_fetcher=readme_fetcher,
        fetch_readme=_fetch_github_readme,
    )


async def enrich_news(
    paper: Dict[str, Any],
    page_fetcher: Optional[PageContentFetcher] = None,
) -> Dict[str, Any]:
    """News 文章：兼容入口，保留模块页面抓取 seam。"""
    return await content_enrichment_coordinator.enrich_news(
        paper,
        page_fetcher=page_fetcher,
        fetch_page=_fetch_url_text,
    )


def enrich_producthunt(paper: Dict[str, Any]) -> Dict[str, Any]:
    """ProductHunt：兼容入口，委托非 PDF 内容协调器。"""
    return content_enrichment_coordinator.enrich_producthunt(paper)


async def enrich_hackernews(
    paper: Dict[str, Any],
    page_fetcher: Optional[PageContentFetcher] = None,
) -> Dict[str, Any]:
    """HackerNews：兼容入口，保留模块页面抓取 seam。"""
    return await content_enrichment_coordinator.enrich_hackernews(
        paper,
        page_fetcher=page_fetcher,
        fetch_page=_fetch_url_text,
    )


# ── 批量入口 ──────────────────────────────────────────────────────────────────

_ENRICH_MAP = {
    "arxiv": enrich_arxiv,
    "huggingface": enrich_huggingface,
    "github": enrich_github,
    "news": enrich_news,
    "producthunt": enrich_producthunt,
    "hackernews": enrich_hackernews,
}


async def enrich_papers(
    papers: List[Dict[str, Any]],
    source_key: str,
    delay: float = 0.5,
    *,
    page_fetcher: Optional[PageContentFetcher] = None,
    readme_fetcher: Optional[GitHubReadmeFetcher] = None,
) -> List[Dict[str, Any]]:
    """对一批 paper dict 批量执行内容丰富，返回原列表（就地修改）。

    Args:
        papers: Top-N 筛选后的 paper dict 列表
        source_key: 数据源名称（"arxiv" / "huggingface" / "github" / "news" / "producthunt" / "hackernews"）
        delay: 每条之间的礼貌延迟（秒），避免对目标服务器过于频繁
               注意：arxiv 快速路径（摘要入库）无需延迟
        page_fetcher: News / HackerNews 可注入页面抓取端口；默认保留模块抓取 seam
        readme_fetcher: GitHub 可注入 README 抓取端口；默认保留模块抓取 seam

    Returns:
        就地添加了 full_text 字段的同一列表
    """
    enricher = _ENRICH_MAP.get(source_key)
    if enricher is None:
        logger.warning("[Enricher] 未知数据源 %s，跳过内容丰富。", source_key)
        return papers

    # arxiv 快速路径：摘要入库，无需等待 PDF 下载，不加延迟
    effective_delay = 0.0 if source_key == "arxiv" else delay

    logger.info("[Enricher][%s] 开始内容丰富，共 %d 条...", source_key, len(papers))
    for i, paper in enumerate(papers, 1):
        if paper.get("skip_enrich"):
            paper.setdefault(
                "full_text",
                paper.get("summary")
                or paper.get("abstract")
                or paper.get("title")
                or "",
            )
            logger.debug(
                "[Enricher][%s] #%d 命中已有 summary，跳过 enrich: %s",
                source_key,
                i,
                (paper.get("title") or "")[:50],
            )
            continue

        try:
            if source_key == "github" and readme_fetcher is not None:
                result = enricher(paper, readme_fetcher=readme_fetcher)
            elif source_key in {"news", "hackernews"} and page_fetcher is not None:
                result = enricher(paper, page_fetcher=page_fetcher)
            else:
                result = enricher(paper)
            if asyncio.iscoroutine(result):
                await result
            ft_len = len(paper.get("full_text", ""))
            logger.debug(
                "[Enricher][%s] #%d %s → full_text %d chars",
                source_key,
                i,
                (paper.get("title") or "")[:50],
                ft_len,
            )
        except Exception as exc:
            logger.warning("[Enricher][%s] #%d 内容丰富失败: %s", source_key, i, exc)
            # 兜底：保留原有 abstract
            paper.setdefault(
                "full_text",
                paper.get("abstract")
                or paper.get("summary")
                or paper.get("title")
                or "",
            )

        if effective_delay > 0 and i < len(papers):
            await asyncio.sleep(effective_delay)

    logger.info("[Enricher][%s] 内容丰富完成。", source_key)
    return papers
