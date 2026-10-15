from __future__ import annotations

"""Shared taxonomy and JSON helpers for AI project/tool catalog enrichment."""

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List

PROMPT_VERSION = "v6"

PROJECT_TAXONOMY: List[Dict[str, Any]] = [
    {
        "slug": "productivity_tools",
        "name": "AI 效率工具",
        "children": [
            {"slug": "writing_docs", "name": "写作 / 文档"},
            {"slug": "meetings_email", "name": "会议 / 邮件"},
            {"slug": "browser_search", "name": "浏览器 / 搜索"},
            {"slug": "office_automation", "name": "办公自动化"},
            {"slug": "notes_knowledge", "name": "笔记 / 知识管理"},
            {"slug": "personal_assistant", "name": "个人助手"},
            {"slug": "spreadsheet_analysis", "name": "表格 / 数据分析"},
            {"slug": "productivity_other", "name": "其他效率工具", "default": True},
        ],
    },
    {
        "slug": "coding_tools",
        "name": "AI 编程工具",
        "children": [
            {"slug": "code_generation", "name": "代码生成"},
            {"slug": "code_review", "name": "代码审查"},
            {"slug": "ide_plugins", "name": "IDE / 编辑器插件"},
            {"slug": "testing_ci", "name": "测试 / CI 自动化"},
            {"slug": "dev_agents", "name": "开发智能体"},
            {"slug": "code_search_docs", "name": "代码搜索 / 文档"},
            {"slug": "low_code_scaffold", "name": "低代码 / 脚手架"},
            {"slug": "coding_other", "name": "其他编程工具", "default": True},
        ],
    },
    {
        "slug": "agents_automation",
        "name": "AI Agent / 自动化",
        "children": [
            {"slug": "agent_frameworks", "name": "Agent 框架"},
            {"slug": "multi_agent", "name": "多智能体协作"},
            {"slug": "workflow_automation", "name": "工作流自动化"},
            {"slug": "mcp_tool_use", "name": "MCP / 工具调用"},
            {"slug": "browser_rpa", "name": "浏览器 / RPA 自动化"},
            {"slug": "research_agents", "name": "自主研究助手"},
            {"slug": "personal_automation", "name": "个人自动化助手"},
            {"slug": "agent_other", "name": "其他 Agent 工具", "default": True},
        ],
    },
    {
        "slug": "ai_apps",
        "name": "AI 产品 / 应用",
        "children": [
            {"slug": "chat_clients", "name": "聊天客户端"},
            {"slug": "ai_search_products", "name": "AI 搜索产品"},
            {"slug": "vertical_saas", "name": "垂直 SaaS"},
            {"slug": "desktop_mobile_apps", "name": "桌面 / 移动应用"},
            {"slug": "marketing_sales", "name": "营销 / 销售"},
            {"slug": "education_apps", "name": "教育应用"},
            {"slug": "customer_ops", "name": "客服 / 运营"},
            {"slug": "ai_apps_other", "name": "其他 AI 应用", "default": True},
        ],
    },
    {
        "slug": "learning_resources",
        "name": "AI 教程 / 学习资源",
        "children": [
            {"slug": "awesome_lists", "name": "Awesome List"},
            {"slug": "tutorials_courses", "name": "教程 / 课程"},
            {"slug": "prompt_collections", "name": "Prompt 合集"},
            {"slug": "papers_reading", "name": "论文 / 阅读"},
            {"slug": "examples_templates", "name": "示例 / 模板"},
            {"slug": "newsletters_news", "name": "Newsletter / 资讯"},
            {"slug": "project_collections", "name": "项目集合"},
            {"slug": "learning_other", "name": "其他学习资源", "default": True},
        ],
    },
    {
        "slug": "rag_knowledge",
        "name": "RAG / 知识库",
        "children": [
            {"slug": "vector_search", "name": "向量检索"},
            {"slug": "document_qa", "name": "文档问答"},
            {"slug": "graph_rag", "name": "GraphRAG"},
            {"slug": "enterprise_knowledge", "name": "企业知识库"},
            {"slug": "retrieval_infra", "name": "检索基础设施"},
            {"slug": "ai_search_engine", "name": "AI 搜索引擎"},
            {"slug": "document_parsing", "name": "文档解析"},
            {"slug": "rag_other", "name": "其他知识库工具", "default": True},
        ],
    },
    {
        "slug": "multimodal_tools",
        "name": "多模态工具",
        "children": [
            {"slug": "image_generation", "name": "图像生成"},
            {"slug": "video_generation", "name": "视频生成"},
            {"slug": "speech_audio", "name": "语音 / 音频"},
            {"slug": "ocr_vision", "name": "OCR / 视觉理解"},
            {"slug": "multimodal_chat", "name": "多模态聊天"},
            {"slug": "creative_design", "name": "创意设计"},
            {"slug": "three_d_spatial", "name": "3D / 空间内容"},
            {"slug": "multimodal_other", "name": "其他多模态工具", "default": True},
        ],
    },
    {
        "slug": "models_infra",
        "name": "模型 / 推理 / 部署",
        "children": [
            {"slug": "local_llm_runtime", "name": "本地 LLM 运行"},
            {"slug": "inference_serving", "name": "推理服务"},
            {"slug": "llm_gateway", "name": "LLM Gateway"},
            {"slug": "model_deploy_mlops", "name": "模型部署 / MLOps"},
            {"slug": "model_compression_accel", "name": "模型压缩 / 加速"},
            {"slug": "edge_runtime", "name": "边缘运行时"},
            {"slug": "model_management", "name": "模型管理"},
            {"slug": "models_infra_other", "name": "其他模型基础设施", "default": True},
        ],
    },
    {
        "slug": "data_eval_training",
        "name": "数据 / 评测 / 训练",
        "children": [
            {"slug": "datasets", "name": "数据集"},
            {"slug": "benchmark_eval", "name": "Benchmark / Eval"},
            {"slug": "fine_tuning", "name": "微调"},
            {"slug": "synthetic_data", "name": "合成数据"},
            {"slug": "training_frameworks", "name": "训练框架"},
            {"slug": "observability", "name": "可观测性"},
            {"slug": "data_labeling_cleaning", "name": "数据标注 / 清洗"},
            {"slug": "data_training_other", "name": "其他数据训练工具", "default": True},
        ],
    },
    {
        "slug": "security_privacy",
        "name": "安全 / 隐私",
        "children": [
            {"slug": "prompt_security", "name": "Prompt 安全"},
            {"slug": "privacy_local_first", "name": "隐私 / 本地优先"},
            {"slug": "redteam_eval", "name": "红队 / 安全评测"},
            {"slug": "compliance_guardrails", "name": "合规 / Guardrails"},
            {"slug": "vulnerability_analysis", "name": "漏洞分析"},
            {"slug": "content_safety", "name": "内容安全"},
            {"slug": "security_other", "name": "其他安全隐私工具", "default": True},
        ],
    },
    {
        "slug": "other",
        "name": "其他",
        "children": [
            {"slug": "other_uncategorized", "name": "未分类", "default": True},
        ],
    },
]

WEBSITE_TAXONOMY: List[Dict[str, Any]] = [
    {
        "slug": "productivity_tools",
        "name": "效率 / 搜索工具",
        "children": [
            {"slug": "writing_docs", "name": "写作 / 文档"},
            {"slug": "meetings_email", "name": "办公协作"},
            {"slug": "browser_search", "name": "搜索 / 导航"},
            {"slug": "office_automation", "name": "在线办公"},
            {"slug": "notes_knowledge", "name": "笔记 / 知识库"},
            {"slug": "personal_assistant", "name": "个人助手"},
            {"slug": "spreadsheet_analysis", "name": "表格 / 数据分析"},
            {"slug": "productivity_other", "name": "其他效率网站", "default": True},
        ],
    },
    {
        "slug": "coding_tools",
        "name": "开发 / 设计工具",
        "children": [
            {"slug": "code_generation", "name": "代码 / 开发"},
            {"slug": "code_review", "name": "代码审查 / 质量"},
            {"slug": "ide_plugins", "name": "IDE / 插件"},
            {"slug": "testing_ci", "name": "测试 / CI"},
            {"slug": "dev_agents", "name": "开发 Agent"},
            {"slug": "code_search_docs", "name": "开发文档 / 检索"},
            {"slug": "low_code_scaffold", "name": "低代码 / 模板"},
            {"slug": "coding_other", "name": "其他开发网站", "default": True},
        ],
    },
    {
        "slug": "agents_automation",
        "name": "Agent / 自动化网站",
        "children": [
            {"slug": "agent_frameworks", "name": "Agent 框架"},
            {"slug": "multi_agent", "name": "多 Agent 协作"},
            {"slug": "workflow_automation", "name": "工作流自动化"},
            {"slug": "mcp_tool_use", "name": "MCP / 工具调用"},
            {"slug": "browser_rpa", "name": "浏览器 / RPA"},
            {"slug": "research_agents", "name": "研究助手"},
            {"slug": "personal_automation", "name": "个人自动化"},
            {"slug": "agent_other", "name": "其他自动化网站", "default": True},
        ],
    },
    {
        "slug": "ai_apps",
        "name": "在线产品 / SaaS",
        "children": [
            {"slug": "chat_clients", "name": "聊天 / 对话"},
            {"slug": "ai_search_products", "name": "AI 搜索"},
            {"slug": "vertical_saas", "name": "垂直 SaaS"},
            {"slug": "desktop_mobile_apps", "name": "桌面 / 移动应用"},
            {"slug": "marketing_sales", "name": "营销 / 销售"},
            {"slug": "education_apps", "name": "教育应用"},
            {"slug": "customer_ops", "name": "客服 / 运营"},
            {"slug": "ai_apps_other", "name": "其他在线产品", "default": True},
        ],
    },
    {
        "slug": "learning_resources",
        "name": "教程 / 资料",
        "children": [
            {"slug": "awesome_lists", "name": "资源合集"},
            {"slug": "tutorials_courses", "name": "教程 / 课程"},
            {"slug": "prompt_collections", "name": "Prompt 资源"},
            {"slug": "papers_reading", "name": "论文 / 阅读"},
            {"slug": "examples_templates", "name": "示例 / 模板"},
            {"slug": "newsletters_news", "name": "资讯 / Newsletter"},
            {"slug": "project_collections", "name": "项目集合"},
            {"slug": "learning_other", "name": "其他资料网站", "default": True},
        ],
    },
    {
        "slug": "rag_knowledge",
        "name": "知识库 / 文档工具",
        "children": [
            {"slug": "vector_search", "name": "检索 / 搜索"},
            {"slug": "document_qa", "name": "文档问答"},
            {"slug": "graph_rag", "name": "图谱知识"},
            {"slug": "enterprise_knowledge", "name": "企业知识库"},
            {"slug": "retrieval_infra", "name": "检索基础设施"},
            {"slug": "ai_search_engine", "name": "搜索引擎"},
            {"slug": "document_parsing", "name": "文档解析"},
            {"slug": "rag_other", "name": "其他知识网站", "default": True},
        ],
    },
    {
        "slug": "multimodal_tools",
        "name": "创意 / 媒体工具",
        "children": [
            {"slug": "image_generation", "name": "图片 / 设计"},
            {"slug": "video_generation", "name": "视频"},
            {"slug": "speech_audio", "name": "语音 / 音频"},
            {"slug": "ocr_vision", "name": "OCR / 视觉"},
            {"slug": "multimodal_chat", "name": "多模态对话"},
            {"slug": "creative_design", "name": "创意设计"},
            {"slug": "three_d_spatial", "name": "3D / 空间"},
            {"slug": "multimodal_other", "name": "其他媒体网站", "default": True},
        ],
    },
    {
        "slug": "models_infra",
        "name": "API / 基础设施",
        "children": [
            {"slug": "local_llm_runtime", "name": "本地运行"},
            {"slug": "inference_serving", "name": "推理服务"},
            {"slug": "llm_gateway", "name": "API 网关"},
            {"slug": "model_deploy_mlops", "name": "部署 / MLOps"},
            {"slug": "model_compression_accel", "name": "压缩 / 加速"},
            {"slug": "edge_runtime", "name": "边缘运行"},
            {"slug": "model_management", "name": "模型管理"},
            {"slug": "models_infra_other", "name": "其他基础设施", "default": True},
        ],
    },
    {
        "slug": "data_eval_training",
        "name": "数据 / 分析平台",
        "children": [
            {"slug": "datasets", "name": "数据集"},
            {"slug": "benchmark_eval", "name": "评测 / 榜单"},
            {"slug": "fine_tuning", "name": "微调"},
            {"slug": "synthetic_data", "name": "合成数据"},
            {"slug": "training_frameworks", "name": "训练平台"},
            {"slug": "observability", "name": "监控 / 可观测"},
            {"slug": "data_labeling_cleaning", "name": "标注 / 清洗"},
            {"slug": "data_training_other", "name": "其他数据网站", "default": True},
        ],
    },
    {
        "slug": "security_privacy",
        "name": "安全 / 隐私社区",
        "children": [
            {"slug": "prompt_security", "name": "Prompt 安全"},
            {"slug": "privacy_local_first", "name": "隐私 / 本地优先"},
            {"slug": "redteam_eval", "name": "红队 / 评测"},
            {"slug": "compliance_guardrails", "name": "合规 / 防护"},
            {"slug": "vulnerability_analysis", "name": "漏洞 / 安全资讯"},
            {"slug": "content_safety", "name": "内容安全"},
            {"slug": "security_other", "name": "其他安全网站", "default": True},
        ],
    },
    {
        "slug": "other",
        "name": "其他网站",
        "children": [
            {"slug": "other_uncategorized", "name": "未分类", "default": True},
        ],
    },
]

# Slugs are the stable contract; English labels are deterministic taxonomy data, never
# inferred from stored descriptions. Legacy ``name`` remains the Chinese label.
ENGLISH_LABEL_BY_SLUG = {
    "productivity_tools": "AI Productivity Tools", "writing_docs": "Writing / Documents",
    "meetings_email": "Meetings / Email", "browser_search": "Browser / Search",
    "office_automation": "Office Automation", "notes_knowledge": "Notes / Knowledge Management",
    "personal_assistant": "Personal Assistant", "spreadsheet_analysis": "Spreadsheets / Data Analysis",
    "productivity_other": "Other Productivity Tools", "coding_tools": "AI Coding Tools",
    "code_generation": "Code Generation", "code_review": "Code Review",
    "ide_plugins": "IDE / Editor Plugins", "testing_ci": "Testing / CI Automation",
    "dev_agents": "Development Agents", "code_search_docs": "Code Search / Documentation",
    "low_code_scaffold": "Low-Code / Scaffolding", "coding_other": "Other Coding Tools",
    "agents_automation": "AI Agents / Automation", "agent_frameworks": "Agent Frameworks",
    "multi_agent": "Multi-Agent Collaboration", "workflow_automation": "Workflow Automation",
    "mcp_tool_use": "MCP / Tool Use", "browser_rpa": "Browser / RPA Automation",
    "research_agents": "Research Agents", "personal_automation": "Personal Automation",
    "agent_other": "Other Agent Tools", "ai_apps": "AI Products / Applications",
    "chat_clients": "Chat Clients", "ai_search_products": "AI Search Products",
    "vertical_saas": "Vertical SaaS", "desktop_mobile_apps": "Desktop / Mobile Apps",
    "marketing_sales": "Marketing / Sales", "education_apps": "Education Apps",
    "customer_ops": "Customer Service / Operations", "ai_apps_other": "Other AI Applications",
    "learning_resources": "AI Tutorials / Learning Resources", "awesome_lists": "Awesome Lists",
    "tutorials_courses": "Tutorials / Courses", "prompt_collections": "Prompt Collections",
    "papers_reading": "Papers / Reading", "examples_templates": "Examples / Templates",
    "newsletters_news": "Newsletters / News", "project_collections": "Project Collections",
    "learning_other": "Other Learning Resources", "rag_knowledge": "RAG / Knowledge Bases",
    "vector_search": "Vector Search", "document_qa": "Document Q&A", "graph_rag": "GraphRAG",
    "enterprise_knowledge": "Enterprise Knowledge Bases", "retrieval_infra": "Retrieval Infrastructure",
    "ai_search_engine": "AI Search Engines", "document_parsing": "Document Parsing",
    "rag_other": "Other Knowledge Tools", "multimodal_tools": "Multimodal Tools",
    "image_generation": "Image Generation", "video_generation": "Video Generation",
    "speech_audio": "Speech / Audio", "ocr_vision": "OCR / Vision Understanding",
    "multimodal_chat": "Multimodal Chat", "creative_design": "Creative Design",
    "three_d_spatial": "3D / Spatial Content", "multimodal_other": "Other Multimodal Tools",
    "models_infra": "Models / Inference / Deployment", "local_llm_runtime": "Local LLM Runtimes",
    "inference_serving": "Inference Serving", "llm_gateway": "LLM Gateways",
    "model_deploy_mlops": "Model Deployment / MLOps", "model_compression_accel": "Model Compression / Acceleration",
    "edge_runtime": "Edge Runtimes", "model_management": "Model Management",
    "models_infra_other": "Other Model Infrastructure", "data_eval_training": "Data / Evaluation / Training",
    "datasets": "Datasets", "benchmark_eval": "Benchmarks / Evaluation", "fine_tuning": "Fine-Tuning",
    "synthetic_data": "Synthetic Data", "training_frameworks": "Training Frameworks",
    "observability": "Observability", "data_labeling_cleaning": "Data Labeling / Cleaning",
    "data_training_other": "Other Data and Training Tools", "security_privacy": "Security / Privacy",
    "prompt_security": "Prompt Security", "privacy_local_first": "Privacy / Local-First",
    "redteam_eval": "Red Teaming / Security Evaluation", "compliance_guardrails": "Compliance / Guardrails",
    "vulnerability_analysis": "Vulnerability Analysis", "content_safety": "Content Safety",
    "security_other": "Other Security and Privacy Tools", "other": "Other",
    "other_uncategorized": "Uncategorized",
}


def _add_bilingual_labels(taxonomy: List[Dict[str, Any]]) -> None:
    for category in taxonomy:
        category["name_zh"] = category["name"]
        category["name_en"] = ENGLISH_LABEL_BY_SLUG[category["slug"]]
        for child in category.get("children", []):
            child["name_zh"] = child["name"]
            child["name_en"] = ENGLISH_LABEL_BY_SLUG[child["slug"]]


_add_bilingual_labels(PROJECT_TAXONOMY)
_add_bilingual_labels(WEBSITE_TAXONOMY)


def _categories_from_taxonomy(taxonomy: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    return [{key: item[key] for key in ("slug", "name", "name_zh", "name_en")} for item in taxonomy]


def _subcategories_from_taxonomy(taxonomy: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, str]]]:
    return {
        item["slug"]: [
            {key: child[key] for key in ("slug", "name", "name_zh", "name_en")}
            for child in item.get("children", [])
        ]
        for item in taxonomy
    }


def _default_subcategory_by_category(taxonomy: List[Dict[str, Any]]) -> Dict[str, str]:
    result: Dict[str, str] = {}
    for item in taxonomy:
        children = item.get("children", [])
        if not children:
            continue
        default_child = next((child for child in children if child.get("default")), children[-1])
        result[item["slug"]] = default_child["slug"]
    return result


PROJECT_CATEGORIES = _categories_from_taxonomy(PROJECT_TAXONOMY)
CATEGORY_BY_SLUG = {item["slug"]: item["name"] for item in PROJECT_CATEGORIES}
SUBCATEGORIES_BY_CATEGORY = _subcategories_from_taxonomy(PROJECT_TAXONOMY)
SUBCATEGORY_BY_CATEGORY_SLUG = {
    category_slug: {child["slug"]: child["name"] for child in children}
    for category_slug, children in SUBCATEGORIES_BY_CATEGORY.items()
}
DEFAULT_SUBCATEGORY_BY_CATEGORY = _default_subcategory_by_category(PROJECT_TAXONOMY)

WEBSITE_CATEGORIES = _categories_from_taxonomy(WEBSITE_TAXONOMY)
WEBSITE_CATEGORY_BY_SLUG = {item["slug"]: item["name"] for item in WEBSITE_CATEGORIES}
WEBSITE_SUBCATEGORIES_BY_CATEGORY = _subcategories_from_taxonomy(WEBSITE_TAXONOMY)
WEBSITE_SUBCATEGORY_BY_CATEGORY_SLUG = {
    category_slug: {child["slug"]: child["name"] for child in children}
    for category_slug, children in WEBSITE_SUBCATEGORIES_BY_CATEGORY.items()
}
WEBSITE_DEFAULT_SUBCATEGORY_BY_CATEGORY = _default_subcategory_by_category(WEBSITE_TAXONOMY)


def _category_prompt(taxonomy: List[Dict[str, Any]], extra_hints: List[str]) -> str:
    lines = ["可选 category_slug 与 subcategory_slug（subcategory_slug 必须来自所选 category_slug）："]
    for category in taxonomy:
        lines.append(f"- {category['slug']}：{category['name']}")
        for child in category.get("children", []):
            lines.append(f"  - {child['slug']}：{child['name']}")
    lines.extend(["", "分类优先级提示：", *extra_hints])
    return "\n".join(lines)


CATEGORY_PROMPT = _category_prompt(
    PROJECT_TAXONOMY,
    [
        "- awesome、tutorial、course、prompt collection、build-your-own、papers/list 优先归入 learning_resources。",
        "- coding assistant、Claude Code、Cursor、IDE、code review、test generation 优先归入 coding_tools。",
        "- agent、MCP、workflow、automation、multi-agent 优先归入 agents_automation。",
        "- 直接可用的个人效率/办公/搜索/写作/浏览器工具优先归入 productivity_tools。",
        "- API gateway、serving、local runtime、inference、deployment 优先归入 models_infra。",
        "- 图像、视频、语音、OCR、视觉理解和创意生成优先归入 multimodal_tools。",
        "- 数据集、benchmark、eval、微调、训练、观测优先归入 data_eval_training。",
    ],
)
WEBSITE_CATEGORY_PROMPT = _category_prompt(
    WEBSITE_TAXONOMY,
    [
        "- 按网页本身的用途分类，不按 GitHub 项目形态分类。",
        "- 搜索引擎、导航站、常用入口优先归入 productivity_tools / browser_search。",
        "- 安全论坛、漏洞平台、技术安全媒体优先归入 security_privacy。",
        "- 论坛、社区、问答、资讯和内容平台按主要用途选择 learning_resources、security_privacy 或 other。",
        "- API 网关、模型服务、部署平台优先归入 models_infra。",
        "- 无法判断或与 AI 无关的普通网站归入 other。",
    ],
)


@dataclass
class EnrichmentResult:
    category_slug: str
    category_name: str
    subcategory_slug: str
    subcategory_name: str
    description_zh: str
    tags: List[str]
    confidence: float
    description_en: str = ""
    tags_en: List[str] = field(default_factory=list)


def clean_text(value: Any, *, max_len: int = 512) -> str:
    text = str(value or "").strip()
    text = re.sub(r"\s+", " ", text)
    text = text.replace("```", "").strip()
    return text[:max_len]


# CJK 统一表意文字区间（tags_en/description_en 校验与原生描述判定共用同一事实源）。
CJK_PATTERN = r"[㐀-鿿]"

# 原生 GitHub 描述是否不足以服务英文读者的判定口径（英文策展描述补跑圈选依据）：
# 为空、过短（一句话信息量不足）或本身是中文。CJK 占比 0.5 起算中文为主——
# 英文句中夹中文产品名（占比少数）仍视为合格英文，不补。
RAW_DESCRIPTION_ENGLISH_MIN_CHARS = 50
RAW_DESCRIPTION_CJK_MAJORITY_RATIO = 0.5


def raw_description_needs_english(raw_description: Any) -> bool:
    """原生描述是否需要补英文策展文案：空 / <50 字符 / CJK 占比过半。"""
    text = str(raw_description or "").strip()
    if len(text) < RAW_DESCRIPTION_ENGLISH_MIN_CHARS:
        return True
    cjk_chars = len(re.findall(CJK_PATTERN, text))
    return cjk_chars / len(text) >= RAW_DESCRIPTION_CJK_MAJORITY_RATIO


def extract_message_text(message_or_content: Any) -> str:
    """Extract final text from LangChain string or multipart message content."""
    content = getattr(message_or_content, "content", message_or_content)

    if isinstance(content, str):
        return content
    if content is None:
        return ""
    if isinstance(content, dict):
        if "content" in content and not content.get("type"):
            return extract_message_text(content["content"])
        blocks = [content]
    elif isinstance(content, (list, tuple)):
        blocks = content
    else:
        return str(content)

    text_parts: List[str] = []
    for block in blocks:
        if isinstance(block, str):
            text_parts.append(block)
            continue
        if isinstance(block, dict):
            block_type = str(block.get("type") or "").lower()
            text = block.get("text") or block.get("text_delta")
        else:
            block_type = str(getattr(block, "type", "") or "").lower()
            text = getattr(block, "text", None) or getattr(block, "text_delta", None)
        if block_type in {"text", "text_delta", "output_text"} and isinstance(text, str):
            text_parts.append(text)

    return "".join(text_parts)


def parse_json_object(raw: str) -> Dict[str, Any]:
    cleaned = re.sub(r"```(?:json)?", "", raw or "").replace("```", "").strip()
    try:
        data = json.loads(cleaned)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if not match:
            return {}
        try:
            data = json.loads(match.group())
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            return {}


def clamp_confidence(value: Any) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, numeric))


def normalize_tags(
    value: Any,
    fallback: str = "",
    *,
    default: str = "AI 工具",
) -> List[str]:
    if isinstance(value, list):
        raw_tags = value
    elif value:
        raw_tags = str(value).split(",")
    else:
        raw_tags = []

    tags: List[str] = []
    for item in raw_tags:
        tag = clean_text(item, max_len=24)
        if tag and tag not in tags:
            tags.append(tag)
        if len(tags) >= 4:
            break

    if not tags and fallback:
        tags.append(fallback)
    return tags or ([default] if default else [])


def normalize_subcategory(
    category_slug: str,
    value: Any,
    *,
    subcategory_by_category_slug: Dict[str, Dict[str, str]] | None = None,
    default_subcategory_by_category: Dict[str, str] | None = None,
) -> tuple[str, str]:
    subcategory_map = subcategory_by_category_slug or SUBCATEGORY_BY_CATEGORY_SLUG
    default_map = default_subcategory_by_category or DEFAULT_SUBCATEGORY_BY_CATEGORY
    valid_children = subcategory_map.get(category_slug) or {}
    subcategory_slug = clean_text(value, max_len=64)
    if subcategory_slug not in valid_children:
        subcategory_slug = default_map.get(category_slug, "other_uncategorized")
    return subcategory_slug, valid_children.get(subcategory_slug, "未分类")


def normalize_enrichment(
    data: Dict[str, Any],
    *,
    fallback_description: str,
    fallback_tag: str = "",
    category_by_slug: Dict[str, str] | None = None,
    subcategory_by_category_slug: Dict[str, Dict[str, str]] | None = None,
    default_subcategory_by_category: Dict[str, str] | None = None,
) -> EnrichmentResult:
    categories = category_by_slug or CATEGORY_BY_SLUG
    category_slug = clean_text(data.get("category_slug"), max_len=64)
    if category_slug not in categories:
        category_slug = "other"

    subcategory_slug, subcategory_name = normalize_subcategory(
        category_slug,
        data.get("subcategory_slug"),
        subcategory_by_category_slug=subcategory_by_category_slug,
        default_subcategory_by_category=default_subcategory_by_category,
    )

    description_zh = clean_text(data.get("description_zh"), max_len=160)
    if not description_zh:
        description_zh = clean_text(fallback_description, max_len=160)
    # English copy must be model-authored; never derive it from Chinese or raw metadata.
    description_en = clean_text(data.get("description_en"), max_len=320)
    if not description_en:
        raise ValueError("模型必须返回英文描述")
    if re.search(CJK_PATTERN, description_en):
        raise ValueError("英文描述不得包含中文")

    tags = normalize_tags(data.get("tags_zh", data.get("tags")), fallback_tag)
    tags_en = normalize_tags(data.get("tags_en"), default="")
    if not tags_en or len(tags_en) != len(tags):
        raise ValueError("模型必须返回与中文标签一一对应的英文标签")
    if any(re.search(CJK_PATTERN, tag) for tag in tags_en):
        raise ValueError("英文标签不得包含中文")
    return EnrichmentResult(
        category_slug=category_slug,
        category_name=categories[category_slug],
        subcategory_slug=subcategory_slug,
        subcategory_name=subcategory_name,
        description_zh=description_zh,
        tags=tags,
        confidence=clamp_confidence(data.get("confidence")),
        description_en=description_en,
        tags_en=tags_en,
    )
