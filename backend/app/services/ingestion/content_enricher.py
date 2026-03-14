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
import time
from typing import Any, Dict, List, Optional

import httpx
from bs4 import BeautifulSoup

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
    soup = BeautifulSoup(html, "html.parser")
    # 移除脚本、样式、导航等噪音标签
    for tag in soup(
        [
            "script",
            "style",
            "nav",
            "header",
            "footer",
            "aside",
            "form",
            "button",
            "noscript",
            "iframe",
        ]
    ):
        tag.decompose()
    text = soup.get_text(separator="\n")
    # 折叠多余空白行
    lines = [ln.strip() for ln in text.splitlines()]
    lines = [ln for ln in lines if ln]
    return "\n".join(lines)


async def _fetch_url_text(url: str, timeout: int = _HTTP_TIMEOUT) -> str:
    """抓取 URL 页面并返回纯文本，失败返回空字符串。"""
    if not url or not url.startswith("http"):
        return ""
    try:
        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            headers=_HEADERS,
            trust_env=True,
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            ct = resp.headers.get("content-type", "")
            if "html" not in ct and "text" not in ct:
                return ""
            return _clean_html_text(resp.text)
    except Exception as exc:
        logger.debug("[Enricher] 抓取页面失败 %s: %s", url, exc)
        return ""


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
    """通过 GitHub API 获取仓库 README 纯文本（无需 token）。"""
    if not full_name or "/" not in full_name:
        return ""
    try:
        import base64

        api_url = f"https://api.github.com/repos/{full_name}/readme"
        async with httpx.AsyncClient(
            timeout=15,
            follow_redirects=True,
            trust_env=True,
        ) as client:
            resp = await client.get(
                api_url,
                headers={
                    "Accept": "application/vnd.github+json",
                    "User-Agent": "RAG-AIGC-Agent/1.0",
                },
            )
        if resp.status_code in (403, 404, 429):
            return ""
        resp.raise_for_status()
        payload = resp.json()
        content = payload.get("content", "")
        encoding = payload.get("encoding", "")
        if not content or encoding != "base64":
            return ""
        decoded = base64.b64decode(content).decode("utf-8", errors="ignore")
        decoded = re.sub(r"```[\s\S]*?```", " ", decoded)
        decoded = re.sub(r"`[^`]+`", " ", decoded)
        decoded = re.sub(r"!\[[^\]]*\]\([^\)]*\)", " ", decoded)
        decoded = re.sub(r"\[[^\]]+\]\([^\)]*\)", " ", decoded)
        decoded = re.sub(r"[#>*_\-]{1,}", " ", decoded)
        decoded = re.sub(r"\s+", " ", decoded).strip()
        return decoded[:20_000]
    except Exception as exc:
        logger.debug("[Enricher] GitHub README 抓取失败 %s: %s", full_name, exc)
        return ""


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
    """HuggingFace 模型：直接用描述/摘要入 RAG，无需 PDF。

    模型卡片的描述已经足够，不需要额外的 PDF 解析。
    """
    abstract = paper.get("abstract", "") or paper.get("summary", "") or ""
    title = paper.get("title", "")
    pipeline_tag = paper.get("pipeline_tag", "")
    likes = paper.get("likes", 0)
    downloads = paper.get("downloads", 0)

    # 拼接丰富的摘要文本
    parts = []
    if title:
        parts.append(f"# {title}")
    if pipeline_tag:
        parts.append(
            f"Pipeline: {pipeline_tag} | Likes: {likes:,} | Downloads: {downloads:,}"
        )
    if abstract:
        parts.append(abstract)

    full_text = "\n\n".join(parts) if parts else title
    paper["full_text"] = full_text[:_MAX_CONTENT_CHARS]
    paper["pdf_pending"] = False

    logger.debug(
        "[Enricher][HuggingFace] 摘要入库: %s (%d chars)", title[:50], len(full_text)
    )
    return paper


async def enrich_github(paper: Dict[str, Any]) -> Dict[str, Any]:
    """GitHub 仓库：优先使用已有 abstract（含 README），否则重新抓取。

    source_github.py 的 _parse_item 会在 abstract 中拼接 README，
    但 github_hot_service 走 get_github_hot_rank → SQLite，abstract 字段
    只存了 description，需要额外补 README。
    """
    abstract = paper.get("abstract", "") or ""
    full_name = paper.get("full_name") or paper.get("title") or ""

    # 如果 abstract 已包含 README（超过 500 字符）则认为已充分
    if len(abstract) > 500:
        paper["full_text"] = abstract[:_MAX_CONTENT_CHARS]
        return paper

    # 需要额外抓取 README
    readme = ""
    if full_name and "/" in full_name:
        logger.info("[Enricher][GitHub] 补抓 README: %s", full_name)
        readme = await _fetch_github_readme(full_name)

    description = paper.get("description") or paper.get("summary") or abstract
    if readme:
        full_text = f"{description}\n\nREADME:\n{readme}".strip()
    else:
        full_text = description

    paper["full_text"] = full_text[:_MAX_CONTENT_CHARS]
    return paper


async def enrich_news(paper: Dict[str, Any]) -> Dict[str, Any]:
    """News 文章：抓取原文详情页正文；回退到 RSS 摘要。"""
    url = paper.get("url", "")
    summary = paper.get("abstract", "") or paper.get("summary", "") or ""
    title = paper.get("title", "")

    full_text = ""
    if url:
        logger.info("[Enricher][News] 抓取详情页: %s", url[:80])
        page_text = await _fetch_url_text(url)
        if len(page_text) > len(summary) + 200:
            full_text = f"# {title}\n\n{page_text}"

    if not full_text:
        full_text = f"# {title}\n\n{summary}" if summary else title

    paper["full_text"] = full_text[:_MAX_CONTENT_CHARS]
    return paper


def enrich_producthunt(paper: Dict[str, Any]) -> Dict[str, Any]:
    """ProductHunt：保持 tagline + description，不额外抓取。"""
    abstract = paper.get("abstract", "") or paper.get("summary", "") or ""
    title = paper.get("title", "")
    paper["full_text"] = (f"# {title}\n\n{abstract}" if abstract else title)[
        :_MAX_CONTENT_CHARS
    ]
    return paper


async def enrich_hackernews(paper: Dict[str, Any]) -> Dict[str, Any]:
    """HackerNews 帖子：抓取外链正文；Ask HN / Show HN 使用 story_text；回退到标题。"""
    url = paper.get("url", "")
    title = paper.get("title", "")
    story_text = paper.get("abstract", "") or paper.get("summary", "") or ""
    hn_id = paper.get("hn_id", "")

    # HN 内链（Ask HN / Show HN）直接用 story_text
    hn_item_url = f"https://news.ycombinator.com/item?id={hn_id}"
    is_internal = not url or url == hn_item_url or "news.ycombinator.com" in url

    full_text = ""

    if not is_internal and url:
        logger.info("[Enricher][HackerNews] 抓取外链详情页: %s", url[:80])
        page_text = await _fetch_url_text(url)
        if len(page_text) > 200:
            full_text = f"# {title}\n\n{page_text}"

    if not full_text and story_text and story_text != title:
        full_text = f"# {title}\n\n{story_text}"

    if not full_text:
        full_text = title

    paper["full_text"] = full_text[:_MAX_CONTENT_CHARS]
    return paper


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
) -> List[Dict[str, Any]]:
    """对一批 paper dict 批量执行内容丰富，返回原列表（就地修改）。

    Args:
        papers: Top-N 筛选后的 paper dict 列表
        source_key: 数据源名称（"arxiv" / "huggingface" / "github" / "news" / "producthunt" / "hackernews"）
        delay: 每条之间的礼貌延迟（秒），避免对目标服务器过于频繁
               注意：arxiv 快速路径（摘要入库）无需延迟

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


def enrich_arxiv_pdfs_background(
    papers: List[Dict[str, Any]],
    milvus_repo: Optional[Any] = None,
    mysql_repo: Optional[Any] = None,
    delay: float = 2.0,
    max_workers: int = 3,
) -> int:
    """后台异步下载 Arxiv PDF，补充已入库的 full_text。

    在 enrich_papers(arxiv) 快速入库后，由 pipeline 在后台线程调用此函数，
    逐一下载 PDF 并更新 Milvus 向量库中的文档内容。

    Args:
        papers: pdf_pending=True 的 arxiv paper dict 列表
        milvus_repo: MilvusRepository 实例（用于更新向量）
        mysql_repo: MySQLRepository 实例（可选，用于更新 summary 字段）
        delay: 每篇 PDF 下载之间的间隔（秒）
        max_workers: 并行下载线程数

    Returns:
        成功补全 PDF 的数量
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    pending = [p for p in papers if p.get("pdf_pending")]
    if not pending:
        logger.info("[Enricher][Arxiv] 无待补 PDF，跳过后台补全。")
        return 0

    logger.info(
        "[Enricher][Arxiv] 后台 PDF 补全开始，共 %d 篇（max_workers=%d）...",
        len(pending),
        max_workers,
    )
    success_count = 0

    def _do_enrich_one(paper: Dict[str, Any]) -> Dict[str, Any]:
        time.sleep(delay)
        return enrich_arxiv_pdf_full(paper)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_do_enrich_one, p): p for p in pending}
        for future in as_completed(futures):
            paper = futures[future]
            try:
                updated = future.result()
                ft = updated.get("full_text", "")
                if ft and not updated.get("pdf_pending"):
                    success_count += 1
                    # 尝试更新 Milvus（重新 upsert 该文档）
                    if milvus_repo is not None:
                        try:
                            from langchain_core.documents import Document
                            from backend.app.services.ingestion.pipeline import (
                                _doc_id as calc_doc_id,
                            )

                            # 修复 Bug2：用 _doc_id() 计算正确的文档 ID
                            real_doc_id = calc_doc_id(updated)

                            doc = Document(
                                page_content=ft,
                                metadata={
                                    "id": real_doc_id,  # ← 修复 Bug2
                                    "source": updated.get("source", "arxiv"),
                                    "title": updated.get("title", ""),
                                    "published_date": updated.get("published_date", ""),
                                    "url": updated.get("url", ""),
                                    "pdf_url": updated.get("pdf_url", ""),
                                    "raw_score": float(
                                        updated.get("raw_score")
                                        or updated.get("score")
                                        or 0.0
                                    ),
                                    "source_channel": updated.get("source_channel", ""),
                                    "stars": int(updated.get("stars") or 0),
                                    "language": updated.get("language", ""),
                                    "created_at": updated.get("created_at", ""),
                                },
                            )
                            milvus_repo.add_documents([doc], already_split=False)
                            logger.debug(
                                "[Enricher][Arxiv] PDF 补全并更新 Milvus: %s (id=%s)",
                                updated.get("arxiv_id", updated.get("title", ""))[:50],
                                real_doc_id,
                            )
                        except Exception as exc:
                            logger.warning(
                                "[Enricher][Arxiv] Milvus 更新失败 %s: %s",
                                updated.get("arxiv_id", ""),
                                exc,
                            )
            except Exception as exc:
                arxiv_id = paper.get("arxiv_id", paper.get("title", ""))
                logger.warning("[Enricher][Arxiv] PDF 补全失败 %s: %s", arxiv_id, exc)

    logger.info(
        "[Enricher][Arxiv] 后台 PDF 补全完成，%d/%d 篇成功。",
        success_count,
        len(pending),
    )
    return success_count
