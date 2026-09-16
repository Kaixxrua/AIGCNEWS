from __future__ import annotations

from typing import Any

from starlette.requests import Request

from backend.app.core.config import settings


def safe_document(row: dict[str, Any]) -> dict[str, Any]:
    """Convert repository values to the scalar representation exposed by REST."""
    result: dict[str, Any] = {}
    for key, value in row.items():
        if isinstance(value, (str, int, float, bool, type(None))):
            result[key] = value
        else:
            result[key] = str(value) if value is not None else None
    return result


def public_base_url(request: Request) -> str:
    """对外站点 origin，仅来自 PUBLIC_BASE_URL 配置；未配置时返回空串。

    绝不从请求派生 origin：request.base_url 由 Host 头构建，X-Forwarded-Proto
    同样可被匿名请求伪造；此前直接采信二者，攻击者可用伪造头污染缓存响应与
    公开响应中的链接域名（缓存投毒/钓鱼链接）。Host 一律不采信，
    X-Forwarded-Proto 在 Host 不可信后单独无法构成绝对 URL，故也不再读取。
    需要绝对 URL 的消费方（MCP 客户端、跨域部署）应配置 PUBLIC_BASE_URL。
    返回空串时调用方生成相对路径（浏览器按同源解析，前端 /api 同源）。
    """
    del request  # 保留签名以兼容既有调用方；不再从请求读取任何内容。
    return (settings.public_base_url or "").rstrip("/")


def project_pdf_media_url(document: dict[str, Any], request: Request) -> dict[str, Any]:
    """Preserve the response shape while retiring local PDF delivery."""
    document["pdf_media_url"] = None
    return document

