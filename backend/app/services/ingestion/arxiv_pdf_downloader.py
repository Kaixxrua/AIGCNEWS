from __future__ import annotations

"""Arxiv PDF 下载器（模块二）

职责：
  1. 通过 arXiv 官方 XML API 批量拉取论文元数据（标题/摘要/作者/日期/PDF URL）
  2. 以"低频慢速"策略将 PDF 落盘到本地 storage/papers/{arxiv_id}.pdf
  3. 用 PyMuPDF (fitz) 解析本地 PDF，提取纯文本
  4. 更新 MySQL documents.local_pdf_path 字段
  5. 将 PDF 全文切片（RecursiveCharacterTextSplitter）后写入 Milvus

防封杀策略：
  - 每次 PDF 下载之间强制 sleep 3-5 秒（可配置）
  - User-Agent 模拟浏览器
  - 30 篇 PDF 哪怕 sleep 5s 也只需约 2.5 分钟
"""

import asyncio
import logging
import os
import re
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional, Tuple

import httpx

logger = logging.getLogger(__name__)

# ── 常量 ──────────────────────────────────────────────────────────────────────

_ARXIV_API_BASE = "https://export.arxiv.org/api/query"
_ARXIV_PDF_BASE = "https://arxiv.org/pdf"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    )
}

# XML namespace
_NS = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}

# PDF 解析最大页数
_PDF_MAX_PAGES = 50
# 正文最大字符数
_MAX_CONTENT_CHARS = 40_000
# 向量切片大小（字符数约 3000 ≈ 800 token）
_CHUNK_SIZE = 3000
_CHUNK_OVERLAP = 200


# ── 模块一：arXiv XML API 拉取元数据 ─────────────────────────────────────────


def _fetch_arxiv_metadata_by_ids(
    arxiv_ids: List[str],
    timeout: int = 30,
) -> List[Dict[str, Any]]:
    """通过 arXiv XML API 批量拉取论文元数据。

    Args:
        arxiv_ids: arXiv ID 列表，如 ["2403.12345", "2312.00001"]
        timeout: HTTP 超时秒数

    Returns:
        paper dict 列表，含 title/abstract/authors/published_date/pdf_url/arxiv_id
    """
    if not arxiv_ids:
        return []

    # arXiv API 支持 id_list 参数，逗号分隔
    id_list = ",".join(arxiv_ids)
    params = {
        "id_list": id_list,
        "max_results": len(arxiv_ids),
    }

    try:
        with httpx.Client(
            timeout=timeout, headers=_HEADERS, follow_redirects=True
        ) as client:
            resp = client.get(_ARXIV_API_BASE, params=params)
            resp.raise_for_status()
            xml_text = resp.text
    except Exception as exc:
        logger.error("[ArxivDownloader] arXiv API 请求失败: %s", exc)
        return []

    return _parse_arxiv_xml(xml_text)


def _parse_arxiv_xml(xml_text: str) -> List[Dict[str, Any]]:
    """解析 arXiv API 返回的 Atom XML，提取论文元数据。"""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        logger.error("[ArxivDownloader] XML 解析失败: %s", exc)
        return []

    papers = []
    for entry in root.findall("atom:entry", _NS):
        try:
            paper = _parse_entry(entry)
            if paper:
                papers.append(paper)
        except Exception as exc:
            logger.warning("[ArxivDownloader] 解析单条 entry 失败: %s", exc)

    logger.info("[ArxivDownloader] arXiv API 解析完成，共 %d 篇。", len(papers))
    return papers


def _parse_entry(entry: ET.Element) -> Optional[Dict[str, Any]]:
    """从单个 <entry> 元素提取论文元数据。"""
    # ID: http://arxiv.org/abs/2403.12345v1 → 2403.12345
    raw_id = (entry.findtext("atom:id", default="", namespaces=_NS) or "").strip()
    arxiv_id = ""
    m = re.search(r"abs/([\d.]+(?:v\d+)?)", raw_id)
    if m:
        arxiv_id = m.group(1).split("v")[0]  # 去掉版本号
    if not arxiv_id:
        return None

    title = (entry.findtext("atom:title", default="", namespaces=_NS) or "").strip()
    title = re.sub(r"\s+", " ", title)

    abstract = (
        entry.findtext("atom:summary", default="", namespaces=_NS) or ""
    ).strip()
    abstract = re.sub(r"\s+", " ", abstract)

    published = (
        entry.findtext("atom:published", default="", namespaces=_NS) or ""
    ).strip()

    authors = []
    for author_el in entry.findall("atom:author", _NS):
        name_el = author_el.find("atom:name", _NS)
        if name_el is not None and name_el.text:
            authors.append(name_el.text.strip())

    # 构建 PDF URL
    pdf_url = f"{_ARXIV_PDF_BASE}/{arxiv_id}"
    hf_url = f"https://huggingface.co/papers/{arxiv_id}"
    original_arxiv_url = f"https://arxiv.org/abs/{arxiv_id}"

    return {
        "arxiv_id": arxiv_id,
        "title": title,
        "abstract": abstract,
        "published_date": published,
        "url": hf_url,
        "original_arxiv_url": original_arxiv_url,
        "pdf_url": pdf_url,
        "authors": authors[:5],
        "source": "arxiv",
        "source_channel": "huggingface_daily_html",
    }


# ── 模块二：本地落盘下载 ──────────────────────────────────────────────────────


def _get_storage_dir() -> str:
    """获取 PDF 存储目录，确保目录存在。"""
    try:
        from backend.app.core.config import settings

        storage_dir = settings.papers_storage_dir
    except Exception:
        storage_dir = os.getenv("PAPERS_STORAGE_DIR", "storage/papers")
    os.makedirs(storage_dir, exist_ok=True)
    return storage_dir


def _local_pdf_path(arxiv_id: str) -> str:
    """返回 arxiv_id 对应的本地 PDF 文件路径（相对路径）。"""
    storage_dir = _get_storage_dir()
    return os.path.join(storage_dir, f"{arxiv_id}.pdf")


def _download_one_pdf(
    arxiv_id: str, pdf_url: str, sleep_seconds: float = 3.0
) -> Optional[str]:
    """下载单篇 PDF 到本地，返回本地相对路径；失败返回 None。

    Args:
        arxiv_id: arXiv ID
        pdf_url:  PDF 下载 URL
        sleep_seconds: 下载前的礼貌等待（防封杀）

    Returns:
        成功时返回相对路径（如 "storage/papers/2403.12345.pdf"），失败返回 None
    """
    local_path = _local_pdf_path(arxiv_id)

    # 已存在则跳过（幂等）
    if os.path.exists(local_path) and os.path.getsize(local_path) > 1024:
        logger.info("[ArxivDownloader] PDF 已存在，跳过下载: %s", local_path)
        return local_path

    # 礼貌等待
    if sleep_seconds > 0:
        logger.debug(
            "[ArxivDownloader] 等待 %.1fs 后下载 %s ...", sleep_seconds, arxiv_id
        )
        time.sleep(sleep_seconds)

    try:
        with httpx.Client(
            timeout=60,
            follow_redirects=True,
            headers=_HEADERS,
        ) as client:
            resp = client.get(pdf_url)
            resp.raise_for_status()
            content_type = resp.headers.get("content-type", "")
            if "pdf" not in content_type.lower() and not pdf_url.lower().endswith(
                ".pdf"
            ):
                logger.warning(
                    "[ArxivDownloader] 响应非 PDF content-type: %s (%s)",
                    content_type,
                    arxiv_id,
                )
                return None

            with open(local_path, "wb") as f:
                f.write(resp.content)

        file_size = os.path.getsize(local_path)
        logger.info(
            "[ArxivDownloader] PDF 落盘成功: %s (%.1f KB)",
            local_path,
            file_size / 1024,
        )
        return local_path

    except Exception as exc:
        logger.warning("[ArxivDownloader] PDF 下载失败 %s: %s", arxiv_id, exc)
        # 清理可能的残破文件
        if os.path.exists(local_path):
            try:
                os.remove(local_path)
            except OSError:
                pass
        return None


# ── 模块三：PyMuPDF 本地解析 ──────────────────────────────────────────────────


def _extract_text_from_local_pdf(local_path: str) -> str:
    """用 PyMuPDF (fitz) 读取本地 PDF，提取前 N 页纯文本。

    优先使用 PyMuPDF，回退到 pdfplumber，再回退到 pypdf。
    """
    if not local_path or not os.path.exists(local_path):
        return ""

    # 优先尝试 PyMuPDF
    try:
        import fitz  # type: ignore  # PyMuPDF

        doc = fitz.open(local_path)
        pages = doc[:_PDF_MAX_PAGES]
        parts = []
        for page in pages:
            try:
                text = page.get_text("text")
                if text:
                    parts.append(text)
            except Exception:
                pass
        doc.close()
        full_text = "\n".join(parts)
        full_text = re.sub(r"\n{3,}", "\n\n", full_text).strip()
        if full_text:
            logger.debug(
                "[ArxivDownloader] PyMuPDF 解析成功: %s (%d chars)",
                local_path,
                len(full_text),
            )
            return full_text[:_MAX_CONTENT_CHARS]
    except ImportError:
        logger.debug("[ArxivDownloader] PyMuPDF 未安装，尝试 pdfplumber...")
    except Exception as exc:
        logger.warning("[ArxivDownloader] PyMuPDF 解析失败 %s: %s", local_path, exc)

    # 回退到 pdfplumber
    try:
        import pdfplumber  # type: ignore

        parts = []
        with pdfplumber.open(local_path) as pdf:
            for page in pdf.pages[:_PDF_MAX_PAGES]:
                try:
                    text = page.extract_text()
                    if text:
                        parts.append(text)
                except Exception:
                    pass
        full_text = "\n".join(parts)
        full_text = re.sub(r"\n{3,}", "\n\n", full_text).strip()
        if full_text:
            logger.debug(
                "[ArxivDownloader] pdfplumber 解析成功: %s (%d chars)",
                local_path,
                len(full_text),
            )
            return full_text[:_MAX_CONTENT_CHARS]
    except ImportError:
        logger.debug("[ArxivDownloader] pdfplumber 未安装，尝试 pypdf...")
    except Exception as exc:
        logger.warning("[ArxivDownloader] pdfplumber 解析失败 %s: %s", local_path, exc)

    # 最终回退到 pypdf
    try:
        import io
        import pypdf  # type: ignore

        with open(local_path, "rb") as f:
            reader = pypdf.PdfReader(io.BytesIO(f.read()))
        parts = []
        for page in reader.pages[:_PDF_MAX_PAGES]:
            try:
                parts.append(page.extract_text() or "")
            except Exception:
                pass
        full_text = "\n".join(parts)
        full_text = re.sub(r"\n{3,}", "\n\n", full_text).strip()
        return full_text[:_MAX_CONTENT_CHARS]
    except ImportError:
        logger.error(
            "[ArxivDownloader] pypdf 也未安装，无法解析 PDF。pip install pymupdf"
        )
    except Exception as exc:
        logger.warning("[ArxivDownloader] pypdf 解析失败 %s: %s", local_path, exc)

    return ""


# ── 模块四：切片 + Milvus 写入 ────────────────────────────────────────────────


def _chunk_and_index(
    paper: Dict[str, Any],
    doc_id: str,
    full_text: str,
    milvus_repo: Any,
    mysql_repo: Any,
) -> bool:
    """将 PDF 全文切片后写入 Milvus，并更新 MySQL local_pdf_path。

    Args:
        paper: paper dict（含 arxiv_id/title/published_date/url/pdf_url 等）
        doc_id: 文档 ID（md5 hash）
        full_text: PDF 提取的纯文本
        milvus_repo: MilvusRepository 实例
        mysql_repo: MySQLRepository 实例（可选）

    Returns:
        True = 成功写入 Milvus
    """
    if not full_text:
        return False

    try:
        from langchain_text_splitters import RecursiveCharacterTextSplitter
        from langchain_core.documents import Document

        abstract = paper.get("abstract", "") or paper.get("summary", "")
        combined = (
            f"Abstract:\n{abstract}\n\nFull Paper:\n{full_text}"
            if abstract
            else full_text
        )

        splitter = RecursiveCharacterTextSplitter(
            chunk_size=_CHUNK_SIZE,
            chunk_overlap=_CHUNK_OVERLAP,
            separators=["\n\n", "\n", ". ", " ", ""],
        )
        chunks = splitter.split_text(combined[:_MAX_CONTENT_CHARS])

        docs = []
        for i, chunk in enumerate(chunks):
            docs.append(
                Document(
                    page_content=chunk,
                    metadata={
                        "id": f"{doc_id}_chunk{i}" if i > 0 else doc_id,
                        "source": paper.get("source", "arxiv"),
                        "title": paper.get("title", ""),
                        "published_date": paper.get("published_date", ""),
                        "url": paper.get("url", ""),
                        "pdf_url": paper.get("pdf_url", ""),
                        "raw_score": float(
                            paper.get("raw_score") or paper.get("score") or 0.0
                        ),
                        "source_channel": paper.get("source_channel", ""),
                        "stars": 0,
                        "language": "",
                        "created_at": "",
                        "chunk_index": i,
                        "total_chunks": len(chunks),
                    },
                )
            )

        if milvus_repo is not None:
            milvus_repo.add_documents(docs, already_split=True)
            logger.info(
                "[ArxivDownloader] Milvus 写入成功: %s (%d chunks)",
                paper.get("arxiv_id", doc_id),
                len(docs),
            )

        return True

    except Exception as exc:
        logger.error(
            "[ArxivDownloader] 切片/Milvus 写入失败 %s: %s",
            paper.get("arxiv_id", ""),
            exc,
        )
        return False


# ── 主入口：后台批量下载 Pipeline ─────────────────────────────────────────────


def download_and_index_arxiv_pdfs(
    papers: List[Dict[str, Any]],
    milvus_repo: Optional[Any] = None,
    mysql_repo: Optional[Any] = None,
    sleep_between: float = 3.0,
    max_workers: int = 1,
) -> Tuple[int, int]:
    """后台批量下载 Arxiv PDF，解析全文，切片写入 Milvus，更新 MySQL。

    "低频慢速"策略：
      - max_workers=1（默认串行，避免并发请求 arXiv）
      - 每篇 PDF 下载前 sleep sleep_between 秒

    Args:
        papers: paper dict 列表，必须含 arxiv_id 和 pdf_url
        milvus_repo: MilvusRepository 实例（可选）
        mysql_repo: MySQLRepository 实例（可选，用于更新 local_pdf_path）
        sleep_between: 每次下载之间的间隔秒数
        max_workers: 并发下载线程数（生产建议保持 1）

    Returns:
        (download_success_count, index_success_count)
    """
    from backend.app.services.ingestion.pipeline import _doc_id as calc_doc_id

    pending = [p for p in papers if p.get("arxiv_id") and p.get("pdf_url")]
    if not pending:
        logger.info("[ArxivDownloader] 无待下载 PDF，跳过。")
        return 0, 0

    logger.info(
        "[ArxivDownloader] 开始后台下载 %d 篇 PDF（sleep=%.1fs, workers=%d）...",
        len(pending),
        sleep_between,
        max_workers,
    )

    download_ok = 0
    index_ok = 0

    def _process_one(paper: Dict[str, Any]) -> Tuple[bool, bool]:
        arxiv_id = paper["arxiv_id"]
        pdf_url = paper["pdf_url"]

        # Step 1: 下载落盘
        local_path = _download_one_pdf(arxiv_id, pdf_url, sleep_seconds=sleep_between)
        if not local_path:
            return False, False

        # Step 2: 更新 MySQL local_pdf_path
        doc_id = calc_doc_id(paper)
        if mysql_repo is not None:
            try:
                mysql_repo.update_document_pdf_path(doc_id, local_path)
                logger.debug(
                    "[ArxivDownloader] MySQL local_pdf_path 更新: %s → %s",
                    arxiv_id,
                    local_path,
                )
            except Exception as exc:
                logger.warning("[ArxivDownloader] MySQL 更新失败 %s: %s", arxiv_id, exc)

        # Step 3: 解析 PDF 文本
        full_text = _extract_text_from_local_pdf(local_path)
        if not full_text:
            logger.warning("[ArxivDownloader] PDF 文本提取为空: %s", local_path)
            return True, False

        # Step 4: 切片写入 Milvus
        indexed = _chunk_and_index(
            paper=paper,
            doc_id=doc_id,
            full_text=full_text,
            milvus_repo=milvus_repo,
            mysql_repo=mysql_repo,
        )
        return True, indexed

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_process_one, p): p for p in pending}
        for future in as_completed(futures):
            paper = futures[future]
            try:
                dl_ok, idx_ok = future.result()
                if dl_ok:
                    download_ok += 1
                if idx_ok:
                    index_ok += 1
            except Exception as exc:
                logger.warning(
                    "[ArxivDownloader] 处理异常 %s: %s",
                    paper.get("arxiv_id", ""),
                    exc,
                )

    logger.info(
        "[ArxivDownloader] 批量处理完成：下载成功 %d/%d，向量化成功 %d/%d。",
        download_ok,
        len(pending),
        index_ok,
        len(pending),
    )
    return download_ok, index_ok


async def download_and_index_arxiv_pdfs_async(
    papers: List[Dict[str, Any]],
    milvus_repo: Optional[Any] = None,
    mysql_repo: Optional[Any] = None,
    sleep_between: float = 3.0,
    max_workers: int = 1,
) -> Tuple[int, int]:
    """异步包装器：在线程池中运行阻塞的下载 Pipeline，不阻塞事件循环。"""
    return await asyncio.to_thread(
        download_and_index_arxiv_pdfs,
        papers,
        milvus_repo,
        mysql_repo,
        sleep_between,
        max_workers,
    )
