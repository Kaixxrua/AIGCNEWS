#!/usr/bin/env python3
"""Backfill authors/arxiv_id for existing arXiv documents.

存量 arXiv 文档入库时未持久化作者（persistence_adapter 曾丢弃采集器解析
结果）。本脚本从 documents.url 推导 arxiv_id（并用文档主键的 md5 规则做
一致性校验），分批调用 arXiv Atom API（id_list）补齐 authors/arxiv_id。
幂等：仅扫描 authors 仍为空的行；--after-id 支持断点续跑；--dry-run 零写入。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.core.postgres_database import postgres_database  # noqa: E402
from backend.app.repositories.application_repository_context import (  # noqa: E402
    configure_application_repositories,
)
from backend.app.repositories.application_repository_factory import (  # noqa: E402
    create_application_repositories,
)
from backend.app.services.ingestion.arxiv_pdf_downloader import (  # noqa: E402
    _fetch_arxiv_metadata_by_ids,
)

# url 三类宿主：arxiv.org/abs|pdf/<id>、huggingface.co/papers/<id> 与
# hf-mirror.com/papers/<id>（HF 镜像域名，存量约两成），兼容 v 后缀
_ARXIV_ID_RE = re.compile(
    r"(?:arxiv\.org/(?:abs|pdf)/|(?:huggingface\.co|hf-mirror\.com)/papers/)([0-9]{4}\.[0-9]{4,5})(?:v\d+)?"
)
_MAX_AUTHORS = 5


def _derive_arxiv_id(url: str) -> str:
    match = _ARXIV_ID_RE.search(url or "")
    return match.group(1) if match else ""


def _document_id_matches(arxiv_id: str, doc_id: str) -> bool:
    """镜像 document_projection.document_id 的 arXiv 主键规则做 sanity 校验。"""
    return hashlib.md5(f"arxiv:{arxiv_id}".encode()).hexdigest() == doc_id


def backfill_authors(
    documents: Any,
    fetcher: Callable[[list[str]], list[dict[str, Any]]] = _fetch_arxiv_metadata_by_ids,
    *,
    after_id: str = "",
    limit: int = 500,
    batch_size: int = 100,
    sleep_seconds: float = 3.0,
    dry_run: bool = False,
) -> dict[str, Any]:
    rows = documents.list_arxiv_documents_missing_authors(after_id=after_id, limit=limit)
    result: dict[str, Any] = {
        "status": "dry_run" if dry_run else "success",
        "scanned": len(rows),
        "missing_id": 0,
        "id_mismatch": 0,
        "fetched": 0,
        "updated": 0,
        "planned_updates": 0,
        "last_id": rows[-1]["id"] if rows else after_id,
        "samples": [],
    }
    pending: list[tuple[str, str]] = []  # (doc_id, arxiv_id)
    for row in rows:
        arxiv_id = _derive_arxiv_id(row.get("url") or "")
        if not arxiv_id:
            result["missing_id"] += 1
            continue
        if not _document_id_matches(arxiv_id, row["id"]):
            result["id_mismatch"] += 1
            continue
        pending.append((row["id"], arxiv_id))

    batch_size = max(1, min(int(batch_size), 200))
    for offset in range(0, len(pending), batch_size):
        chunk = pending[offset : offset + batch_size]
        papers = fetcher([arxiv_id for _, arxiv_id in chunk])
        result["fetched"] += len(papers)
        authors_by_id = {
            paper["arxiv_id"]: paper.get("authors") or []
            for paper in papers
            if paper.get("arxiv_id")
        }
        for doc_id, arxiv_id in chunk:
            authors = authors_by_id.get(arxiv_id) or []
            if not authors:
                continue
            result["planned_updates"] += 1
            if len(result["samples"]) < 5:
                result["samples"].append({"id": doc_id, "arxiv_id": arxiv_id, "authors": authors[:_MAX_AUTHORS]})
            if not dry_run:
                documents.update_document_authors(
                    doc_id,
                    json.dumps(authors[:_MAX_AUTHORS], ensure_ascii=False),
                    arxiv_id,
                )
                result["updated"] += 1
        if offset + batch_size < len(pending):
            time.sleep(max(0.0, sleep_seconds))  # arXiv API 礼貌限速（约 3s/请求）

    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Backfill authors/arxiv_id for arXiv documents")
    parser.add_argument("--after-id", default="")
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--sleep", type=float, default=3.0)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repositories = create_application_repositories(postgres=postgres_database)
    configure_application_repositories(repositories)
    result = backfill_authors(
        repositories.documents,
        after_id=args.after_id,
        limit=args.limit,
        batch_size=args.batch_size,
        sleep_seconds=args.sleep,
        dry_run=args.dry_run,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    postgres_database.close()
    return 0 if result["status"] in {"success", "dry_run"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
