from __future__ import annotations

import re

_ARXIV_ID_RE = re.compile(r"(\d{4}\.\d{4,5}(?:v\d+)?)")

ARXIV_REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; AIGC-News-Bot/1.0; "
        "+https://github.com/aigc-news)"
    ),
    "Accept": "application/pdf,*/*",
}


def extract_arxiv_id(url_or_id: str) -> str | None:
    match = _ARXIV_ID_RE.search(url_or_id or "")
    return match.group(1) if match else None


def arxiv_pdf_url(arxiv_id: str) -> str:
    return f"https://arxiv.org/pdf/{arxiv_id}.pdf"


def pdf_response_headers(arxiv_id: str) -> dict[str, str]:
    # 前端 pdf.js 经 public_base_url 同源加载该响应，无需也不应放开
    # Access-Control-Allow-Origin: *（CORS 白名单统一由 main.py 中间件收口）
    return {
        "Content-Disposition": f'inline; filename="{arxiv_id}.pdf"',
        "Cache-Control": "public, max-age=86400",
    }
