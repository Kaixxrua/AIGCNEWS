#!/usr/bin/env python3
"""Re-check every stored arXiv summary against the arXiv API and HF paper pages.

旧版 HF 详情页解析有两类缺陷，arXiv API 尚未收录（无法补全）的当日新论文
带着错误摘要入库，跌出榜单后不再重采，错误值一直留在库里：
1. 逐节点 strip 吞掉词间空格——整段无空格，或只丢链接词两侧的空格
   （"has garnered growingattention"）；
2. 关键词噪声过滤把含 "Code:" / "Project page:" / "thanks to" 的真摘要整段
   丢掉，改取 AI 一句话总结、评论区段落，或干脆留空。
另外旧入库口径把论文摘要一律截到 500 字（停在半个词上），现改存完整摘要。
这些缺陷都无法用 SQL 条件圈定，本脚本逐行复核全部 arXiv 文档：
1. arXiv API 批量取权威摘要（每批 50 篇）：与之逐字一致即 unchanged；正是
   其前 500 字即 api_truncated——补回全文；去掉空白后是其前缀即
   api_whitespace——同一段文字，按 API 原文恢复空格并补全；
2. 其余行（误取段落、为空、LaTeX 写法不同、摘要已修订等）再逐篇抓 HF 详情页，
   按修复后的解析取 Abstract 区块判定：
   - abstract_truncated：库中摘要正是真摘要的前 500 字——补回全文；
   - abstract_prefix：库中摘要去空白后是真摘要的前缀——恢复空格并补全；
   - other_paragraph：库中摘要去空白后是页面上其他段落（AI 总结、评论等）的
     前缀——有出处证明是误取，换成真摘要；
   - fill_empty：库中摘要为空——填入真摘要；
   - unchanged：已与真摘要一致；
   - no_match / no_abstract / fetch_failed / not_checked：页面摘要已修订、段落
     已删除、页面无摘要、抓取失败或熔断后未查——跳过并列出，不写入任何
     不确定的内容。
HF 页面限流为每 IP 每 5 分钟 100 次且与定时采集共用，抓取按响应头
ratelimit 自适应：剩余配额低于 --hf-reserve 即等到窗口重置，为采集留足余量。
写入均为条件更新（库中仍是读出时的值才写），不踩并发采集的新写入。
幂等；--after-id 断点续跑（进度行打印到 stderr）；--dry-run 零写入。
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

import httpx  # noqa: E402
from bs4 import BeautifulSoup  # noqa: E402

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
from backend.app.services.ingestion.persistence_adapter import (  # noqa: E402
    summary_limit,
)
from backend.app.services.ingestion.source_arxiv_mcp import (  # noqa: E402
    _abstract_section_text,
    _get_headers,
    _hf_papers_base,
    _node_text,
)

# 与 persistence_adapter.project_document_write 的 arXiv 摘要截断同口径。
_SUMMARY_LIMIT = summary_limit("arxiv")
# 旧入库口径：非 X 源摘要一律截到 500 字。
_LEGACY_SUMMARY_LIMIT = 500
_WHITESPACE_RE = re.compile(r"\s+")
_RATELIMIT_RE = re.compile(r"\br=(\d+);t=(\d+)")
_WRITE_ACTIONS = (
    "api_truncated",
    "api_whitespace",
    "abstract_truncated",
    "abstract_prefix",
    "other_paragraph",
    "fill_empty",
)
_SKIP_ACTIONS = (
    "no_match",
    "no_abstract",
    "fetch_failed",
    "not_checked",
    "api_failed",
    "missing_id",
)
_SAMPLES_PER_ACTION = 3
_MAX_LISTED = 200


def _squash(text: str) -> str:
    return _WHITESPACE_RE.sub("", text or "")


def _legacy_truncated(stored: str, abstract: str) -> bool:
    """库中摘要正是旧入库口径截下的前 500 字。"""
    return len(abstract) > _LEGACY_SUMMARY_LIMIT and stored == abstract[:_LEGACY_SUMMARY_LIMIT]


def classify_against_api(stored: str, api_abstract: str) -> tuple[str, str] | None:
    """对照 arXiv API 摘要判定；无法仅凭 API 判定（需查 HF 页面）时返回 None。"""
    if not api_abstract:
        return None
    summary = api_abstract[:_SUMMARY_LIMIT]
    if stored == summary:
        return "unchanged", summary
    if _legacy_truncated(stored, api_abstract):
        return "api_truncated", summary
    stored_key = _squash(stored)
    if stored_key and _squash(api_abstract).startswith(stored_key):
        return "api_whitespace", summary
    return None


def classify_summary(stored: str, html: str) -> tuple[str, str]:
    """对照 HF 详情页判定库中摘要的处理动作，返回 (动作, 应写入的摘要)。"""
    soup = BeautifulSoup(html, "html.parser")
    abstract = _abstract_section_text(soup)
    if not abstract:
        return "no_abstract", ""
    summary = abstract[:_SUMMARY_LIMIT]
    if stored == summary:
        return "unchanged", summary
    if _legacy_truncated(stored, abstract):
        return "abstract_truncated", summary
    stored_key = _squash(stored)
    if not stored_key:
        return "fill_empty", summary
    if _squash(abstract).startswith(stored_key):
        return "abstract_prefix", summary
    # 旧解析只会取页面上的某个 <p>：库中值能在其他段落里找到出处，才证明是
    # 误取的 AI 总结 / 评论段；找不到出处（摘要已修订等）一律不动。
    if any(_squash(_node_text(p)).startswith(stored_key) for p in soup.find_all("p")):
        return "other_paragraph", summary
    return "no_match", summary


def _fetch_api_abstracts(
    fetch_abstracts: Callable[[list[str]], list[dict[str, Any]]],
    arxiv_ids: list[str],
    *,
    batch_size: int,
    sleep_seconds: float,
) -> tuple[dict[str, str], set[str]]:
    """分批取 API 摘要，返回 (id -> 规整后的摘要, 整批请求失败的 id)。"""
    abstracts: dict[str, str] = {}
    failed: set[str] = set()
    batch_size = max(1, min(int(batch_size), 100))
    for offset in range(0, len(arxiv_ids), batch_size):
        if offset:
            time.sleep(max(0.0, sleep_seconds))  # arXiv API 礼貌限速（约 3s/请求）
        chunk = arxiv_ids[offset : offset + batch_size]
        papers = fetch_abstracts(chunk)
        if not papers:
            # 取数函数吞掉网络错误返回空表：整批标记失败，不能退回逐篇抓 HF。
            failed.update(chunk)
            continue
        for paper in papers:
            if paper.get("arxiv_id"):
                abstracts[paper["arxiv_id"]] = " ".join(str(paper.get("abstract") or "").split())
    return abstracts, failed


def repair_summaries(
    documents: Any,
    fetch_abstracts: Callable[[list[str]], list[dict[str, Any]]],
    fetch_page: Callable[[str], str],
    *,
    after_id: str = "",
    limit: int = 500,
    batch_size: int = 50,
    api_sleep_seconds: float = 3.0,
    page_sleep_seconds: float = 1.0,
    max_consecutive_failures: int = 3,
    dry_run: bool = False,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    rows = documents.list_arxiv_document_summaries(after_id=after_id, limit=limit)
    counts = dict.fromkeys(("unchanged", *_WRITE_ACTIONS, *_SKIP_ACTIONS), 0)
    result: dict[str, Any] = {
        "status": "dry_run" if dry_run else "success",
        "scanned": len(rows),
        "counts": counts,
        "pages_fetched": 0,
        "planned_updates": 0,
        "updated": 0,
        "raced": 0,
        "last_id": rows[-1]["id"] if rows else after_id,
        "planned": [],
        "skipped": [],
        "samples": [],
    }
    sampled = dict.fromkeys(_WRITE_ACTIONS, 0)
    arxiv_ids = [aid for aid in dict.fromkeys(str(row.get("arxiv_id") or "").strip() for row in rows) if aid]
    api_abstracts, api_failed = _fetch_api_abstracts(
        fetch_abstracts, arxiv_ids, batch_size=batch_size, sleep_seconds=api_sleep_seconds
    )

    consecutive_failures = 0
    for index, row in enumerate(rows, start=1):
        arxiv_id = str(row.get("arxiv_id") or "").strip()
        stored = row.get("summary")
        stored_text = str(stored or "")
        if not arxiv_id:
            action, summary = "missing_id", ""
        elif arxiv_id in api_failed:
            action, summary = "api_failed", ""
        else:
            verdict = classify_against_api(stored_text, api_abstracts.get(arxiv_id, ""))
            if verdict is not None:
                action, summary = verdict
            elif consecutive_failures >= max(1, int(max_consecutive_failures)):
                action, summary = "not_checked", ""  # 熔断：HF 连续失败后不再请求
            else:
                if result["pages_fetched"]:
                    time.sleep(max(0.0, page_sleep_seconds))
                result["pages_fetched"] += 1
                try:
                    html = fetch_page(arxiv_id)
                except Exception:  # noqa: BLE001 - 单篇失败只记账，不中断整批
                    consecutive_failures += 1
                    action, summary = "fetch_failed", ""
                else:
                    consecutive_failures = 0
                    action, summary = classify_summary(stored_text, html)
        _record(result, sampled, row, arxiv_id, stored_text, action, summary)
        if progress and index % 100 == 0:
            progress(f"progress {index}/{len(rows)} last_id={row['id']} {json.dumps(counts)}")
        if action not in _WRITE_ACTIONS or dry_run:
            continue
        if documents.update_document_summary_if_unchanged(row["id"], stored, summary):
            result["updated"] += 1
        else:
            result["raced"] += 1
    return result


def _record(
    result: dict[str, Any],
    sampled: dict[str, int],
    row: dict[str, Any],
    arxiv_id: str,
    stored: str,
    action: str,
    summary: str,
) -> None:
    result["counts"][action] += 1
    if action == "unchanged":
        return
    entry = {"id": row["id"], "arxiv_id": arxiv_id, "action": action}
    if action in _SKIP_ACTIONS:
        if len(result["skipped"]) < _MAX_LISTED:
            result["skipped"].append(entry)
        return
    result["planned_updates"] += 1
    if len(result["planned"]) < _MAX_LISTED:
        result["planned"].append(entry)
    if sampled[action] < _SAMPLES_PER_ACTION:
        sampled[action] += 1
        result["samples"].append({**entry, "before": stored[:100], "after": summary[:100]})


class HfPageFetcher:
    """按 HF 限流响应头自适应节流的详情页抓取器。

    响应头形如 ratelimit: "pages";r=<剩余>;t=<距窗口重置秒数>。剩余配额低于
    reserve 时等到窗口重置再继续，把余量留给定时采集；遇 429 等重置后重试一次。
    """

    def __init__(
        self,
        client: httpx.Client,
        *,
        reserve: int = 50,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._client = client
        self._reserve = max(0, int(reserve))
        self._sleep = sleep

    def __call__(self, arxiv_id: str) -> str:
        for attempt in range(2):
            response = self._client.get(f"{_hf_papers_base()}/{arxiv_id}")
            match = _RATELIMIT_RE.search(response.headers.get("ratelimit", ""))
            remaining, reset = (int(match[1]), int(match[2])) if match else (None, 60)
            if response.status_code == 429 and attempt == 0:
                self._sleep(reset + 1)
                continue
            response.raise_for_status()
            if remaining is not None and remaining < self._reserve:
                self._sleep(reset + 1)
            return response.text
        raise AssertionError("unreachable")  # pragma: no cover - 第二轮必返回或抛错


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Re-check stored arXiv summaries against the arXiv API and HF pages"
    )
    parser.add_argument("--after-id", default="")
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--batch-size", type=int, default=50)
    parser.add_argument("--api-sleep", type=float, default=3.0)
    parser.add_argument("--page-sleep", type=float, default=1.0)
    parser.add_argument("--hf-reserve", type=int, default=50)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repositories = create_application_repositories(postgres=postgres_database)
    configure_application_repositories(repositories)
    # 与采集侧 _fetch_paper_details_async 同一套请求头与超时。
    with httpx.Client(headers=_get_headers(), timeout=15, follow_redirects=True) as client:
        result = repair_summaries(
            repositories.documents,
            _fetch_arxiv_metadata_by_ids,
            HfPageFetcher(client, reserve=args.hf_reserve),
            after_id=args.after_id,
            limit=args.limit,
            batch_size=args.batch_size,
            api_sleep_seconds=args.api_sleep,
            page_sleep_seconds=args.page_sleep,
            dry_run=args.dry_run,
            progress=lambda line: print(line, file=sys.stderr, flush=True),
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    postgres_database.close()
    counts = result["counts"]
    return 1 if counts["fetch_failed"] or counts["not_checked"] or counts["api_failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
