from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Tuple

from backend.app.services.rag.raw_openai_streamer import ToolCallResult


TOOL_DEFINITIONS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "query_ranking",
            "description": (
                "查询数据库中的排行榜数据。当用户询问今日/本周/本月的排行榜、"
                "top N、热门项目、trending 等问题时调用此工具。"
                "支持的来源：github、arxiv、news、producthunt、hackernews，"
                "或 all 查询全部来源。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "source": {
                        "type": "string",
                        "enum": [
                            "github",
                            "arxiv",
                            "news",
                            "producthunt",
                            "hackernews",
                            "all",
                        ],
                        "description": "数据来源，all 表示查询所有来源",
                    },
                    "period": {
                        "type": "string",
                        "enum": ["daily", "weekly", "monthly"],
                        "description": "排行周期：daily=日榜，weekly=周榜，monthly=月榜",
                        "default": "daily",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "返回条数，默认 15",
                        "default": 15,
                    },
                },
                "required": ["source"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_knowledge_stats",
            "description": (
                "查询知识库的统计数据和文档列表。当用户询问知识库中有多少文档、"
                "有哪些项目、收录了多少条数据、数据库总量等问题时调用此工具。"
                "返回各来源的文档数量统计和按热度排序的文档列表。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "source": {
                        "type": "string",
                        "enum": [
                            "github",
                            "arxiv",
                            "news",
                            "producthunt",
                            "hackernews",
                            "all",
                        ],
                        "description": "数据来源筛选，all 表示查询所有来源",
                        "default": "all",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "返回文档列表条数，默认 50",
                        "default": 50,
                    },
                },
                "required": [],
            },
        },
    },
]


def execute_query_ranking(
    source: str = "all", period: str = "daily", limit: int = 15
) -> Dict[str, Any]:
    from backend.app.repositories.mysql_repo import MySQLRepository

    db = MySQLRepository()
    tz_cst = timezone(timedelta(hours=8))
    today = datetime.now(tz_cst).strftime("%Y-%m-%d")

    conditions = ["LEFT(created_at, 10) = %s"]
    params: List[Any] = [today]
    if source and source != "all":
        conditions.append("source = %s")
        params.append(source)
    params.append(limit)
    where_clause = " AND ".join(conditions)

    sql = f"""
        SELECT id, source, source_channel, title, url, summary,
               published_date, raw_score, score, rank_in_period, created_at
        FROM documents
        WHERE {where_clause}
        ORDER BY raw_score DESC, rank_in_period ASC
        LIMIT %s
    """

    conn = db._connect()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, tuple(params))
            rows = cur.fetchall()
        conn.commit()
        docs = list(rows)
    finally:
        conn.close()

    period_labels = {"daily": "日", "weekly": "周", "monthly": "月"}
    period_label = period_labels.get(period, "日")
    source_label = (source or "全部来源").upper()
    lines = [f"=== 今日 {source_label} {period_label}榜排行（{today}，共 {len(docs)} 条） ==="]
    for i, doc in enumerate(docs, start=1):
        title = doc.get("title") or "(未知标题)"
        src = doc.get("source") or ""
        url = doc.get("url") or ""
        rank = doc.get("rank_in_period") or i
        raw_score = doc.get("raw_score") or doc.get("score") or 0
        summary = (doc.get("summary") or "")[:200]
        entry = f"第{rank}名 [{src}] {title}"
        if raw_score:
            if src == "github":
                entry += f" (Stars: {int(raw_score)})"
            else:
                entry += f" (分数: {raw_score})"
        if url:
            entry += f"\n  URL: {url}"
        if summary:
            entry += f"\n  简介: {summary}"
        lines.append(entry)
    return {"formatted": "\n".join(lines), "docs": docs, "count": len(docs)}


def execute_query_knowledge_stats(
    source: str = "all", limit: int = 50
) -> Dict[str, Any]:
    from backend.app.repositories.mysql_repo import MySQLRepository

    db = MySQLRepository()
    source_counts = db.documents.get_source_counts()
    conditions: List[str] = []
    params: List[Any] = []
    if source and source != "all":
        conditions.append("source = %s")
        params.append(source)
    params.append(limit)
    where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    sql = f"""
        SELECT id, source, source_channel, title, url, summary,
               published_date, raw_score, score, rank_in_period, created_at
        FROM documents
        {where_clause}
        ORDER BY raw_score DESC, created_at DESC
        LIMIT %s
    """

    conn = db._connect()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, tuple(params))
            rows = cur.fetchall()
        conn.commit()
        docs = list(rows)
    finally:
        conn.close()

    source_label = (source or "全部来源").upper()
    total = sum(source_counts.values())
    lines = [f"=== 知识库 {source_label} 数据统计（实时） ==="]
    lines.append(f"知识库总文档数: {total}")
    for src, cnt in sorted(source_counts.items(), key=lambda x: -x[1]):
        lines.append(f"  - {src}: {cnt} 条")
    if source and source != "all":
        target_count = source_counts.get(source, 0)
        lines.append(f"\n{source} 来源共 {target_count} 条，以下按热度排序前 {limit} 条：")
    lines.append("")
    for i, doc in enumerate(docs, start=1):
        title = doc.get("title") or "(未知标题)"
        src = doc.get("source") or ""
        url = doc.get("url") or ""
        raw_score = doc.get("raw_score") or doc.get("score") or 0
        entry = f"{i}. [{src}] {title}"
        if raw_score:
            if src == "github":
                entry += f" (Stars: {int(raw_score)})"
            else:
                entry += f" (分数: {raw_score})"
        if url:
            entry += f"\n   URL: {url}"
        lines.append(entry)
    return {
        "formatted": "\n".join(lines),
        "docs": docs,
        "source_counts": source_counts,
        "total": total,
    }


TOOL_EXECUTORS: Dict[str, Any] = {
    "query_ranking": execute_query_ranking,
    "query_knowledge_stats": execute_query_knowledge_stats,
}


def build_tool_sources(docs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    sources = []
    seen_urls: set = set()
    for doc in docs:
        url = str(doc.get("url") or "")
        title = str(doc.get("title") or "")
        if not title and not url:
            continue
        dedup_key = url if url else title
        if dedup_key in seen_urls:
            continue
        seen_urls.add(dedup_key)
        sources.append(
            {
                "id": str(doc.get("id") or f"db-{len(sources)}"),
                "score": float(doc.get("raw_score") or doc.get("score") or 0),
                "source": str(doc.get("source") or ""),
                "title": title,
                "url": url,
                "published_date": str(doc.get("published_date") or ""),
            }
        )
    return sources


async def run_tool_calls(
    tool_calls: List[ToolCallResult],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], str]:
    tool_messages: List[Dict[str, Any]] = []
    all_tool_sources: List[Dict[str, Any]] = []
    context_parts: List[str] = []

    async def _exec_one(
        tc: ToolCallResult,
    ) -> Tuple[Dict[str, Any], List[Dict[str, Any]], str]:
        executor = TOOL_EXECUTORS.get(tc.name)
        if executor is None:
            msg = {
                "role": "tool",
                "tool_call_id": tc.id,
                "content": f"未知工具: {tc.name}",
            }
            return msg, [], ""
        try:
            args = json.loads(tc.arguments)
        except json.JSONDecodeError:
            args = {}
        try:
            result = await asyncio.to_thread(executor, **args)
        except Exception as exc:
            msg = {
                "role": "tool",
                "tool_call_id": tc.id,
                "content": f"工具执行出错: {exc}",
            }
            return msg, [], ""
        formatted = result.get("formatted", "")
        docs = result.get("docs", [])
        sources = build_tool_sources(docs)
        msg = {"role": "tool", "tool_call_id": tc.id, "content": formatted}
        return msg, sources, f"[db-query] {formatted}"

    tasks = [_exec_one(tc) for tc in tool_calls]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    for result in results:
        if isinstance(result, Exception):
            print(f"[ChatService] Tool execution error: {result}")
            continue
        message, sources, context = result
        tool_messages.append(message)
        all_tool_sources.extend(sources)
        if context:
            context_parts.append(context)
    return tool_messages, all_tool_sources, "\n\n".join(context_parts)
