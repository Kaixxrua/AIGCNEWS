from __future__ import annotations

"""Hugging Face Trending Models 数据源（M11）

采集 HuggingFace 上按 Likes 排序的热门 AIGC 相关模型。
目的：弥补 Arxiv 和 GitHub 无法覆盖的"模型权重发布"信息。

依赖：huggingface_hub（需在 requirements.txt 中添加）
"""

import logging
from datetime import datetime
from typing import List

logger = logging.getLogger(__name__)

# 仅保留 AIGC 相关 pipeline tags
_AIGC_PIPELINE_TAGS = {
    "text-generation",
    "text2text-generation",
    "text-to-image",
    "image-to-text",
    "image-to-image",
    "summarization",
    "translation",
    "question-answering",
    "conversational",
    "feature-extraction",
    "fill-mask",
    "text-to-video",
    "text-to-audio",
    "text-to-speech",
    "automatic-speech-recognition",
    "visual-question-answering",
    "image-text-to-text",
}


def fetch_hf_trending_models(limit: int = 20) -> List[dict]:
    """从 Hugging Face 获取按 Likes 降序排列的热门 AIGC 模型。

    返回标准化字段列表，兼容 pipeline._to_documents() 格式：
      - title:          Model ID (e.g. meta-llama/Llama-3-70b)
      - abstract:       描述 + Tags + Downloads + Likes 拼接文本
      - summary:        同 abstract
      - url:            https://huggingface.co/{model_id}
      - source:         "huggingface"
      - score:          likes 数
      - tags:           pipeline_tag + 前 5 个 model tags
      - published_date: last_modified 日期
      - likes:          int
      - downloads:      int
      - pipeline_tag:   str
    """
    try:
        from huggingface_hub import HfApi  # type: ignore
    except ImportError:
        logger.error(
            "[HuggingFace] huggingface_hub 未安装，请执行: pip install huggingface_hub"
        )
        return []

    # 广撒网：抓更多数据用于后续过滤，确保经过 AIGC 过滤后仍有足够数量
    fetch_limit = max(limit * 4, 80)

    try:
        api = HfApi()
        models = list(
            api.list_models(
                sort="likes",
                direction=-1,
                limit=fetch_limit,
                cardData=True,  # 获取模型卡片数据（描述等）
                fetch_config=False,
            )
        )
    except Exception as exc:
        logger.error("[HuggingFace] API 调用失败: %s", exc)
        return []

    results: List[dict] = []

    for model in models:
        if len(results) >= limit:
            break

        # 仅保留 AIGC 相关模型
        pipeline_tag = getattr(model, "pipeline_tag", None) or ""
        if pipeline_tag and pipeline_tag not in _AIGC_PIPELINE_TAGS:
            continue

        model_id: str = getattr(model, "modelId", "") or getattr(model, "id", "") or ""
        if not model_id:
            continue

        likes: int = getattr(model, "likes", 0) or 0
        downloads: int = getattr(model, "downloads", 0) or 0
        tags: List[str] = list(getattr(model, "tags", []) or [])

        # 从 cardData 提取描述（前 200 词）
        card_data = getattr(model, "cardData", None) or {}
        raw_desc: str = ""
        if isinstance(card_data, dict):
            raw_desc = str(card_data.get("description", "") or "")
        if not raw_desc:
            # 兜底：尝试从 tags 中重建描述
            raw_desc = f"{pipeline_tag} model" if pipeline_tag else ""

        # 截取前 200 词
        words = raw_desc.split()
        desc_snippet = " ".join(words[:200]) + ("..." if len(words) > 200 else "")

        summary = (
            f"{desc_snippet}  "
            f"[Pipeline: {pipeline_tag}]  "
            f"[Downloads: {downloads:,}]  "
            f"[Likes: {likes:,}]  "
            f"[Tags: {', '.join(tags[:5])}]"
        ).strip()

        # 日期处理
        last_modified = getattr(model, "lastModified", None) or getattr(
            model, "last_modified", None
        )
        published_date = ""
        if last_modified:
            try:
                if isinstance(last_modified, datetime):
                    published_date = last_modified.strftime("%Y-%m-%d")
                else:
                    published_date = str(last_modified)[:10]
            except Exception:
                published_date = ""

        results.append(
            {
                "title": model_id,
                "abstract": summary,
                "summary": summary,
                "url": f"https://huggingface.co/{model_id}",
                "pdf_url": "",
                "source": "huggingface",
                "score": float(likes),
                "tags": ([pipeline_tag] if pipeline_tag else []) + tags[:5],
                "published_date": published_date,
                "likes": likes,
                "downloads": downloads,
                "pipeline_tag": pipeline_tag,
            }
        )

    logger.info(
        "[HuggingFace] 采集完成，共 %d 条 AIGC 模型（原始 %d 条）。",
        len(results),
        len(models),
    )
    return results
