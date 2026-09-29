#!/usr/bin/env python3
"""Repair arXiv document summaries that lost every inter-word space.

HF 论文详情页的摘要逐字符水合渲染，旧解析逐节点 strip 把词间空格全部
吞掉（"Longvisualtokensequences…"）；arXiv API 尚未收录的当日新论文便带着
残缺摘要入库，之后跌出榜单不再重采，残缺值一直留在库里。
本脚本分批调用 arXiv Atom API（id_list）取权威摘要，只在「去掉空白后与
残缺值逐字符吻合」时按入库口径（前 500 字符）覆盖；条件更新（库中仍是
读出时的残缺值才写）避免踩掉并发采集的新写入。
幂等：只扫描仍残缺的行；--after-id 支持断点续跑；--dry-run 零写入。
"""
from __future__ import annotations

import argparse
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

# 与 persistence_adapter.project_document_write 的非 X 源摘要截断同口径。
_SUMMARY_LIMIT = 500
_WHITESPACE_RE = re.compile(r"\s+")


def _squash(text: str) -> str:
    return _WHITESPACE_RE.sub("", text or "")


def repair_summaries(
    documents: Any,
    fetcher: Callable[[list[str]], list[dict[str, Any]]] = _fetch_arxiv_metadata_by_ids,
    *,
    after_id: str = "",
    limit: int = 500,
    batch_size: int = 50,
    sleep_seconds: float = 3.0,
    dry_run: bool = False,
) -> dict[str, Any]:
    rows = documents.list_arxiv_documents_with_collapsed_summary(after_id=after_id, limit=limit)
    result: dict[str, Any] = {
        "status": "dry_run" if dry_run else "success",
        "scanned": len(rows),
        "missing_id": 0,
        "not_found": 0,
        "mismatch": 0,
        "planned_updates": 0,
        "updated": 0,
        "raced": 0,
        "last_id": rows[-1]["id"] if rows else after_id,
        "samples": [],
        "mismatches": [],
    }
    pending = [row for row in rows if str(row.get("arxiv_id") or "").strip()]
    result["missing_id"] = len(rows) - len(pending)

    batch_size = max(1, min(int(batch_size), 100))
    for offset in range(0, len(pending), batch_size):
        chunk = pending[offset : offset + batch_size]
        papers = fetcher([str(row["arxiv_id"]).strip() for row in chunk])
        abstracts = {
            paper["arxiv_id"]: " ".join(str(paper.get("abstract") or "").split())
            for paper in papers
            if paper.get("arxiv_id")
        }
        for row in chunk:
            arxiv_id = str(row["arxiv_id"]).strip()
            abstract = abstracts.get(arxiv_id) or ""
            if not abstract:
                result["not_found"] += 1
                continue
            collapsed = str(row.get("summary") or "")
            # 残缺值 = HF 摘要去空格后的前 500 字符；API 摘要去空白后须以它
            # 开头才算同一段文字，否则宁可跳过也不写入不确定的内容。
            if not _squash(abstract).startswith(_squash(collapsed)):
                result["mismatch"] += 1
                if len(result["mismatches"]) < 5:
                    result["mismatches"].append({"id": row["id"], "arxiv_id": arxiv_id})
                continue
            summary = abstract[:_SUMMARY_LIMIT]
            result["planned_updates"] += 1
            if len(result["samples"]) < 3:
                result["samples"].append({"id": row["id"], "arxiv_id": arxiv_id, "summary": summary[:120]})
            if dry_run:
                continue
            if documents.update_collapsed_document_summary(row["id"], collapsed, summary):
                result["updated"] += 1
            else:
                result["raced"] += 1
        if offset + batch_size < len(pending):
            time.sleep(max(0.0, sleep_seconds))  # arXiv API 礼貌限速（约 3s/请求）

    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Repair arXiv summaries that lost every space")
    parser.add_argument("--after-id", default="")
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--batch-size", type=int, default=50)
    parser.add_argument("--sleep", type=float, default=3.0)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repositories = create_application_repositories(postgres=postgres_database)
    configure_application_repositories(repositories)
    result = repair_summaries(
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
