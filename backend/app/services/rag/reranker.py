"""
Cross-Encoder Reranker（本地精排，无 API 限流风险，支持国内镜像）
----------------------------------------------------
使用 sentence-transformers Cross-Encoder 模型对检索结果进行二次精排。

Cross-Encoder 将 query + document 拼接后一起编码，比 Bi-Encoder（各自独立编码）
精度高得多，能真正区分"与 query 相关"和"语义相似但不相关"。

模型选择：
  - ms-marco-MiniLM-L-6-v2：英文最佳性价比，模型小（22MB），速度快
  - ms-marco-MiniLM-L-12-v2：英文更高精度，稍慢
  - BAAI/bge-reranker-base：中英双语，适合中文查询场景（推荐）
  - BAAI/bge-reranker-large：中英双语高精度，较慢

首次运行会自动下载模型到 ~/.cache/huggingface/
"""

from __future__ import annotations

import asyncio
import os
from typing import List, Optional, Tuple

from langchain_core.documents import Document
from backend.app.core.config import settings

# 支持通过 .env 中的 HF_ENDPOINT 设置 HuggingFace 镜像（国内加速）
# 优先级：os.environ 已有值 > settings.hf_endpoint > 默认 hf-mirror.com
_hf_endpoint = (
    os.environ.get("HF_ENDPOINT") or settings.hf_endpoint or "https://hf-mirror.com"
)
os.environ["HF_ENDPOINT"] = _hf_endpoint

# 强制使用本地缓存，跳过 HuggingFace Hub 的网络请求（避免国内网络超时 2 分钟）
# 模型已缓存到 ~/.cache/huggingface/hub/ 后，每次加载都无需联网
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

# Cross-Encoder 相关性分数阈值（logit 分数，经 sigmoid 后约为概率）
# ms-marco 模型：> 0 表示相关（sigmoid(0)=0.5），通常 > 2 才算强相关
# bge-reranker：分数范围类似，> 0 相关
# 注意：GitHub 项目标题+摘要片段文本较短，bge-reranker-base 对短文本打分偏低
# 设为 0.7（介于相关文档 ~1 和无关文档 ~0 之间，有效过滤噪音）
# bge-reranker-v2-m3 实测：openclaw 相关文档 ~0.985，无关文档 ~0.000
RELEVANCE_THRESHOLD = 0.7

# 一次精排最多处理的文档数
MAX_DOCS_TO_RERANK = 20

# Cross-Encoder 模型名称（首次使用自动下载）
# bge-reranker-v2-m3：多语言高精度（中英双语效果更好），2.27GB（需要足够内存）
# bge-reranker-base：中英双语，1.1GB（内存不足时备选）
# cross-encoder/ms-marco-MiniLM-L-6-v2：纯英文，90MB，速度最快
CROSS_ENCODER_MODEL = "BAAI/bge-reranker-v2-m3"

# 全局单例，避免重复加载模型（模块导入时同步加载，避免请求时阻塞）
_cross_encoder: Optional[object] = None


def _load_cross_encoder_sync() -> Optional[object]:
    """同步加载 Cross-Encoder 模型，模块导入时调用一次。"""
    try:
        from sentence_transformers import CrossEncoder

        print(f"[Reranker] Loading Cross-Encoder: {CROSS_ENCODER_MODEL}")
        model = CrossEncoder(
            CROSS_ENCODER_MODEL,
            max_length=512,
            local_files_only=True,
        )
        print(f"[Reranker] Cross-Encoder loaded successfully.")
        return model
    except Exception as exc:
        print(f"[Reranker] Failed to load Cross-Encoder (will skip rerank): {exc}")
        return None


# 模块导入时在线程中加载，不阻塞 import 但保证第一个请求到来前已完成
import threading as _threading

_load_event = _threading.Event()


def _preload_in_bg():
    global _cross_encoder
    _cross_encoder = _load_cross_encoder_sync()
    _load_event.set()


_bg_thread = _threading.Thread(target=_preload_in_bg, daemon=True)
_bg_thread.start()


async def _get_cross_encoder():
    """获取 Cross-Encoder 模型，等待后台预加载完成（最多 60 秒，超时则跳过）。"""
    global _cross_encoder
    if _cross_encoder is not None:
        return _cross_encoder

    # 后台线程还在加载，等待最多 60 秒（bge-reranker-v2-m3 约 2.27GB，需要更长时间）
    def _wait():
        _load_event.wait(timeout=60.0)
        return _cross_encoder

    try:
        result = await asyncio.wait_for(asyncio.to_thread(_wait), timeout=62.0)
        return result
    except asyncio.TimeoutError:
        print("[Reranker] Timeout waiting for model, skipping rerank")
        return None


async def rerank(
    query: str,
    docs: List[Document],
    threshold: float = RELEVANCE_THRESHOLD,
    max_docs: int = MAX_DOCS_TO_RERANK,
) -> List[Document]:
    """
    用 Cross-Encoder 对文档进行二次精排。

    只对 retriever='vector' 的文档应用阈值过滤，
    其他 fallback 文档保留在上下文中，不展示为来源。

    Args:
        query: 用户查询
        docs: 待精排文档列表
        threshold: Cross-Encoder 分数阈值（logit），低于此值的 vector 文档过滤掉
        max_docs: 最多精排文档数

    Returns:
        按相关性分数降序排列的文档列表（metadata 注入 rerank_score，0-10 分）
    """
    if not docs:
        return []

    candidates = docs[:max_docs]

    # 仅对 vector/hybrid 文档做精排；fallback 文档直接透传，避免大量无意义打分阻塞
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

    try:
        cross_encoder = await _get_cross_encoder()
    except Exception as exc:
        print(f"[Reranker] Failed to load Cross-Encoder, skipping rerank: {exc}")
        return rerank_targets + passthrough_docs

    # 构建 (query, document_text) 对
    pairs: List[Tuple[str, str]] = []
    for doc in rerank_targets:
        meta = doc.metadata or {}
        title = str(meta.get("title") or "")
        content = doc.page_content[:400].strip()
        doc_text = f"{title}\n{content}".strip() or "(empty)"
        pairs.append((query, doc_text))

    # Cross-Encoder 批量打分（在线程中运行避免阻塞事件循环）
    def _score_all() -> List[float]:
        scores = cross_encoder.predict(pairs)  # type: ignore[attr-defined]
        return [float(s) for s in scores]

    try:
        raw_scores = await asyncio.wait_for(asyncio.to_thread(_score_all), timeout=8.0)
    except asyncio.TimeoutError:
        print("[Reranker] Cross-Encoder scoring timeout, skipping rerank")
        return rerank_targets + passthrough_docs
    except Exception as exc:
        print(f"[Reranker] Cross-Encoder scoring failed: {exc}")
        return rerank_targets + passthrough_docs

    # 过滤 + 注入分数
    scored: List[Tuple[float, Document]] = []
    for doc, raw_score in zip(rerank_targets, raw_scores):
        meta = doc.metadata or {}
        retriever_type = str(meta.get("retriever") or "")
        title = str(meta.get("title") or "")[:40]

        print(
            f"[Reranker] score={raw_score:.3f} retriever={retriever_type} title={title!r}"
        )

        # vector 文档：必须通过阈值
        if retriever_type == "vector" and raw_score < threshold:
            continue

        doc.metadata = dict(meta)
        # 将 logit 分数转为 0-10 显示分（用 sigmoid 归一化再缩放）
        import math

        sigmoid = 1.0 / (1.0 + math.exp(-raw_score))
        doc.metadata["rerank_score"] = round(sigmoid * 10, 1)
        scored.append((raw_score, doc))

    scored.sort(key=lambda x: x[0], reverse=True)
    ranked = [doc for _, doc in scored]

    vector_count = sum(
        1
        for doc in ranked
        if str((doc.metadata or {}).get("retriever") or "") == "vector"
    )
    print(
        f"[Reranker] reranked={len(rerank_targets)} passthrough={len(passthrough_docs)} → {len(ranked)} passed ({vector_count} vector, threshold={threshold})"
    )
    return ranked + passthrough_docs
