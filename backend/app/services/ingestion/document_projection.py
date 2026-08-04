from __future__ import annotations

import hashlib
from typing import Iterable

from langchain_core.documents import Document


def document_id(paper: dict) -> str:
    """Return the stable content identity used across ingestion periods."""
    source = paper.get("source", "")

    arxiv_id = paper.get("arxiv_id")
    if arxiv_id:
        return hashlib.md5(f"arxiv:{arxiv_id}".encode()).hexdigest()

    if source == "github":
        key = (
            paper.get("full_name")
            or paper.get("title")
            or paper.get("url")
            or str(paper)
        )
        return hashlib.md5(f"github:{key}".encode()).hexdigest()

    if source == "x":
        # 推文以 tweet_id 为稳定身份，避免 URL 策略漂移导致重复入库
        tweet_id = paper.get("tweet_id")
        if tweet_id:
            return hashlib.md5(f"x:{tweet_id}".encode()).hexdigest()

    key = paper.get("url") or paper.get("title") or str(paper)
    return hashlib.md5(f"{source}:{key}".encode()).hexdigest()


def project_documents(papers: Iterable[dict]) -> list[Document]:
    """Project raw ingestion records to the shared document representation."""
    documents: list[Document] = []
    for paper in papers:
        raw_stars = paper.get("stars")
        try:
            stars = int(raw_stars) if raw_stars is not None else 0
        except (TypeError, ValueError):
            stars = 0

        metadata = {
            "id": document_id(paper),
            "source": paper.get("source", "unknown"),
            "title": paper.get("title") or "",
            "published_date": paper.get("published_date") or "",
            "url": paper.get("url") or "",
            "pdf_url": paper.get("pdf_url") or "",
            "raw_score": float(paper.get("score") or 0.0),
            "source_channel": paper.get(
                "source_channel", paper.get("channel", "")
            )
            or "",
            "stars": stars,
            "language": paper.get("language") or "",
            "created_at": paper.get("created_at") or "",
            "in_daily": int(paper.get("in_daily", 0)),
            "in_weekly": int(paper.get("in_weekly", 0)),
            "in_monthly": int(paper.get("in_monthly", 0)),
        }
        page_content = (
            paper.get("full_text")
            or paper.get("abstract")
            or paper.get("summary")
            or paper.get("title")
            or ""
        )
        documents.append(Document(page_content=page_content, metadata=metadata))
    return documents


def paper_identity_keys(paper: dict) -> list[str]:
    """Return summary lookup identities in their established precedence."""
    keys = [f"id:{document_id(paper)}"]

    url = (paper.get("url") or "").strip()
    if url:
        keys.append(f"url:{url}")

    title = (paper.get("title") or "").strip()
    if title:
        keys.append(f"title:{title}")
    return keys


def sort_papers_for_write(papers: Iterable[dict]) -> list[dict]:
    """Return the deterministic cross-source persistence order."""
    return sorted(
        papers,
        key=lambda paper: (
            paper.get("source", ""),
            paper.get("source_channel", paper.get("channel", "")),
            paper.get("published_date", ""),
            document_id(paper),
        ),
    )


def select_top_for_write(papers: list[dict], top_n: int) -> list[dict]:
    """Mutate to raw-score order, select Top-N, then stabilize write order."""
    if not papers:
        return []

    papers.sort(
        key=lambda paper: float(
            paper.get("raw_score") or paper.get("score") or 0
        ),
        reverse=True,
    )
    return sort_papers_for_write(papers[:top_n])
