"""关键词追踪的中译英扩展：中文词整词命中词表时，也匹配它的英文同义词。

资讯里英文来源（新闻、Hacker News、arXiv、Product Hunt）占多数，只按中文原词
匹配会让中文关键词几乎看不到英文内容。只扩展整词（「智能体平台」不扩展），
英文关键词不扩展，中文同义词也不互相扩展。
"""
from __future__ import annotations

import unicodedata
from functools import cache
from typing import Any

from backend.app.domain.search_semantics import han_concept_english_aliases

# 项目搜索的概念表为项目库而建，下列英文别名在资讯里多指别的意思，追踪时不用。
_AMBIGUOUS_IN_NEWS = frozenset({
    "learning",  # 入门、教程：machine learning、deep learning 会刷屏
    "notes",  # 笔记：release notes、「X notes that…」
    "metrics",  # 监控：评测指标
    "budget",  # 记账、账单：财政预算
})
# 中文词本身在 AI 资讯里有歧义时不扩展：「代理」多指 agent，词表却译作 proxy、vpn。
_AMBIGUOUS_TERMS = frozenset({"代理"})

# 概念表缺少的常见 AI 资讯词，只用于追踪，不改项目搜索。
# 匹配时守英文词边界并允许复数 s，这里只写单数。
_NEWS_TERMS: dict[str, tuple[str, ...]] = {
    "人工智能": ("artificial intelligence",),
    "生成式ai": ("generative ai", "genai"),
    "生成式人工智能": ("generative ai", "genai"),
    "智能体": ("agentic",),
    "多模态": ("multimodal", "multi-modal"),
    "强化学习": ("reinforcement learning",),
    "具身智能": ("embodied ai", "embodied intelligence", "embodied agent"),
    "机器人": ("robot", "robotics"),
    "人形机器人": ("humanoid", "humanoid robot"),
    "开源": ("open source", "open-source", "open-weight", "open weights"),
    "芯片": ("chip", "semiconductor"),
    "算力": ("compute", "computing power", "gpu"),
    "自动驾驶": ("autonomous driving", "self-driving", "robotaxi"),
    "世界模型": ("world model",),
    "扩散模型": ("diffusion model",),
    "数据集": ("dataset",),
    "推理模型": ("reasoning model",),
    "长上下文": ("long context", "long-context"),
    "模型上下文协议": ("model context protocol", "mcp"),
    "语音": ("speech", "voice"),
    "对齐": ("alignment",),
    "幻觉": ("hallucination",),
    "蒸馏": ("distillation",),
    "量化": ("quantization", "quantized"),
    "端侧": ("on-device",),
    "知识图谱": ("knowledge graph",),
    "文生视频": ("text to video", "text-to-video"),
    "安全": ("safety", "security"),
    "融资": ("funding", "fundraising", "seed round", "series a", "series b", "series c"),
    "英伟达": ("nvidia",),
    "谷歌": ("google",),
    "微软": ("microsoft",),
    "苹果": ("apple",),
    "亚马逊": ("amazon",),
    "特斯拉": ("tesla",),
    "字节跳动": ("bytedance",),
    "阿里巴巴": ("alibaba",),
    "阿里": ("alibaba",),
    "阿里云": ("alibaba cloud",),
    "腾讯": ("tencent",),
    "百度": ("baidu",),
    "华为": ("huawei",),
    "小米": ("xiaomi",),
    "深度求索": ("deepseek",),
    "月之暗面": ("moonshot ai", "kimi"),
    "智谱": ("zhipu", "glm"),
    "通义千问": ("qwen",),
    "通义": ("qwen", "tongyi"),
    "千问": ("qwen",),
    "豆包": ("doubao",),
    "文心一言": ("ernie",),
    "文心": ("ernie",),
    "混元": ("hunyuan",),
    "可灵": ("kling",),
    "马斯克": ("elon musk", "musk"),
    "奥特曼": ("sam altman", "altman"),
    "黄仁勋": ("jensen huang",),
    "扎克伯格": ("zuckerberg",),
}


def _key(term: str) -> str:
    return unicodedata.normalize("NFKC", term).strip().casefold()


@cache
def _equivalents() -> dict[str, tuple[str, ...]]:
    merged: dict[str, list[str]] = {}
    for phrase, aliases in (*han_concept_english_aliases().items(), *_NEWS_TERMS.items()):
        bucket = merged.setdefault(_key(phrase), [])
        bucket.extend(alias for alias in aliases if alias not in _AMBIGUOUS_IN_NEWS and alias not in bucket)
    return {
        # 匹配时已允许复数 s，agents 这类复数别名不再单列。
        phrase: tuple(alias for alias in aliases if not (alias.endswith("s") and alias[:-1] in aliases))
        for phrase, aliases in merged.items()
        if aliases and phrase not in _AMBIGUOUS_TERMS
    }


def english_equivalents(term: str) -> tuple[str, ...]:
    """中文追踪词的英文同义词；不在词表里或本身是英文时返回空。"""
    return _equivalents().get(_key(term), ())


def rule_expansions(rule: dict[str, Any]) -> list[dict[str, Any]]:
    """规则里会扩展的关键词与排除词，预览据此说明为什么命中了英文内容。"""
    terms = [(term, False) for term in rule["query"].split()] if rule["kind"] == "keyword" else []
    terms += [(term, True) for term in rule["excludes"]]
    return [
        {"term": term, "aliases": list(aliases), "exclude": exclude}
        for term, exclude in terms
        if (aliases := english_equivalents(term))
    ]
