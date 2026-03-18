"""
SiliconFlow Reranker（云端 API 精排，调用硅基流动 /v1/rerank 接口）
--------------------------------------------------------------------
使用硅基流动提供的 Pro/BAAI/bge-reranker-v2-m3 模型对检索结果进行二次精排。
相比本地加载 2.27GB 模型，API 方式无需本地 GPU/大内存，冷启动即用。

API 文档：https://docs.siliconflow.cn/reference/rerank
接口地址：POST https://api.siliconflow.cn/v1/rerank
"""

from __future__ import annotations

import asyncio
import math
from typing import List

import httpx
from langchain_core.documents import Document

from backend.app.core.config import settings

# Cross-Encoder 相关性分数阈值（relevance_score 经 sigmoid 后约为概率值）
# SiliconFlow rerank API 返回 relevance_score：范围约 0~1
# 设为 0.7 作为默认阈值（0.5 过低导致参考来源太多且不相关），可在 .env 中通过 RERANKER_THRESHOLD 覆盖
RELEVANCE_THRESHOLD = 0.7

# 一次精排最多处理的文档数
MAX_DOCS_TO_RERANK = 5

_RERANK_URL = "https://api.siliconflow.cn/v1/rerank"
_RERANK_MODEL = "Pro/BAAI/bge-reranker-v2-m3"


async def rerank(
    query: str,
    docs: List[Document],
    threshold: float = RELEVANCE_THRESHOLD,
    max_docs: int = MAX_DOCS_TO_RERANK,
) -> List[Document]:
    """
    调用硅基流动 Rerank API 对文档进行二次精排。

    只对 retriever='vector' 或 'hybrid' 的文档调用 API 精排，
    其他 fallback 文档直接透传，不展示为来源。

    Args:
        query: 用户查询
        docs: 待精排文档列表
        threshold: relevance_score 阈值（低于此值的 vector 文档被过滤）
        max_docs: 最多精排文档数

    Returns:
        按相关性分数降序排列的文档列表（metadata 注入 rerank_score，0-10 分）
    """
    if not docs:
        return []

    api_key = settings.siliconflow_api_key
    if not api_key:
        print("[Reranker] siliconflow_api_key not set, skipping rerank")
        for doc in docs:
            doc.metadata = dict(doc.metadata or {})
            doc.metadata.setdefault("rerank_score", 0.0)
        return docs

    candidates = docs[:max_docs]

    # 分类：需精排 vs 直接透传
    rerank_targets: List[Document] = []
    passthrough_docs: List[Document] = []
    for doc in candidates:
        retriever_type = str((doc.metadata or {}).get("retriever") or "")
        if retriever_type in ("vector", "hybrid"):
            rerank_targets.append(doc)
        else:
            doc.metadata = dict(doc.metadata or {})
            doc.metadata.setdefault("rerank_score", 0.0)
            passthrough_docs.append(doc)

    if not rerank_targets:
        return passthrough_docs

    # 构建文档文本列表
    doc_texts: List[str] = []
    for doc in rerank_targets:
        meta = doc.metadata or {}
        title = str(meta.get("title") or "")
        content = doc.page_content[:400].strip()
        doc_text = f"{title}\n{content}".strip() or "(empty)"
        doc_texts.append(doc_text)

    # 调用 SiliconFlow Rerank API
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": settings.reranker_model_name or _RERANK_MODEL,
        "query": query,
        "documents": doc_texts,
        "return_documents": False,
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(_RERANK_URL, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
    except httpx.TimeoutException:
        print("[Reranker] API request timeout, skipping rerank")
        return rerank_targets + passthrough_docs
    except httpx.HTTPStatusError as exc:
        print(
            f"[Reranker] API error {exc.response.status_code}: {exc.response.text[:200]}, skipping rerank"
        )
        return rerank_targets + passthrough_docs
    except Exception as exc:
        print(f"[Reranker] Unexpected error: {exc}, skipping rerank")
        return rerank_targets + passthrough_docs

    # 解析返回结果
    # SiliconFlow 返回格式：{"results": [{"index": 0, "relevance_score": 0.98}, ...]}
    results = data.get("results", [])
    if not results:
        print("[Reranker] Empty results from API, skipping rerank")
        return rerank_targets + passthrough_docs

    # 建立 index -> score 映射
    score_map: dict[int, float] = {
        item["index"]: float(item.get("relevance_score", 0.0))
        for item in results
        if "index" in item
    }

    # 过滤 + 注入分数
    scored: List[tuple[float, Document]] = []
    for i, doc in enumerate(rerank_targets):
        raw_score = score_map.get(i, 0.0)
        meta = doc.metadata or {}
        retriever_type = str(meta.get("retriever") or "")
        title = str(meta.get("title") or "")[:40]

        print(
            f"[Reranker] score={raw_score:.4f} retriever={retriever_type} title={title!r}"
        )

        # vector 文档：必须通过阈值
        if retriever_type == "vector" and raw_score < threshold:
            continue

        doc.metadata = dict(meta)
        # relevance_score 本身已是 0~1 范围，直接缩放到 0-10 显示分
        doc.metadata["rerank_score"] = round(raw_score * 10, 1)
        scored.append((raw_score, doc))

    scored.sort(key=lambda x: x[0], reverse=True)
    ranked = [doc for _, doc in scored]

    vector_count = sum(
        1
        for doc in ranked
        if str((doc.metadata or {}).get("retriever") or "") == "vector"
    )
    print(
        f"[Reranker] reranked={len(rerank_targets)} passthrough={len(passthrough_docs)}"
        f" → {len(ranked)} passed ({vector_count} vector, threshold={threshold})"
    )
    return ranked + passthrough_docs
