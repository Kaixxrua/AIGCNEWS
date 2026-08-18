from __future__ import annotations

from typing import Any
from urllib.parse import quote

from starlette.requests import Request

from backend.app.core.config import settings
from backend.app.services.papers.presentation import public_base_url

# 自托管部署未配置 PUBLIC_BASE_URL 时，回链仍指向公共实例（品牌站点）。
_BRAND_BASE_URL = "https://aigcnews.cn"
_UTM_TOOL = "utm_source=mcp&utm_medium=tool"
_UTM_RESOURCE = "utm_source=mcp&utm_medium=resource"

# 条目级数据来源打标：条目被 LLM 单独引用/复制出响应上下文时仍携带提供方标识。
# 与 item["result_origin"] 互补——result_origin 记记录出处（aigc_news_local /
# github_api_fallback），data_source 恒为提供方品牌域，不随兜底路径变化。
MCP_PROJECT_DATA_SOURCE = "aigcnews.cn"


def _base_url(request: Request | None) -> str:
    if request is not None:
        return public_base_url(request) or _BRAND_BASE_URL
    # handler 单测允许 context=None：此时与 public_base_url 同语义地直读配置。
    return (settings.public_base_url or "").rstrip("/") or _BRAND_BASE_URL


def mcp_attribution(request: Request | None) -> str:
    """品牌署名行：供 LLM 在回答中引用，刻意不带 UTM 保持引用文本干净。"""
    return f"Data provided by AIGC Radar · {_base_url(request)}"


def enrich_doc_detail_url(doc: dict[str, Any], request: Request | None) -> dict[str, Any]:
    """为 arXiv 文档附加站内阅读页回链；其他 source 无站内详情页，置 None。"""
    doc_id = str(doc.get("id") or "").strip()
    if doc.get("source") == "arxiv" and doc_id:
        doc["detail_url"] = (
            f"{_base_url(request)}/papers/{quote(doc_id, safe='')}/read?{_UTM_TOOL}"
        )
    else:
        doc["detail_url"] = None
    return doc


def tag_project_data_source(item: dict[str, Any]) -> dict[str, Any]:
    """项目条目强制打标提供方数据来源；就地修改并返回同一 dict 便于链式调用。"""
    item["data_source"] = MCP_PROJECT_DATA_SOURCE
    return item


def enrich_project_detail_url(item: dict[str, Any], request: Request | None) -> dict[str, Any]:
    """项目库条目回链：站内暂无项目详情页，落到按 full_name 过滤的项目库视图。"""
    full_name = str(item.get("full_name") or "").strip()
    if full_name:
        item["detail_url"] = (
            f"{_base_url(request)}/projects?q={quote(full_name, safe='')}&{_UTM_TOOL}"
        )
    else:
        item["detail_url"] = None
    return item


def briefing_attribution_footer(request: Request | None, locale: str) -> str:
    """report/latest markdown 尾部来源行，随 locale 中英切换。"""
    url = f"{_base_url(request)}/report?{_UTM_RESOURCE}"
    if (locale or "").lower().startswith("en"):
        return (
            f"\n\n---\n*Source: [AIGC Radar · aigcnews.cn]({url})"
            " — full rankings & the AI project library.*"
        )
    return (
        f"\n\n---\n*数据来源：[AIGC Radar · aigcnews.cn]({url})"
        "——完整榜单与 AI 项目库。*"
    )
