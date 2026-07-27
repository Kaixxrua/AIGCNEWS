from __future__ import annotations

import os
from typing import Any

from starlette.requests import Request


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
    base_url = str(request.base_url).rstrip("/")
    forwarded_proto = request.headers.get("x-forwarded-proto", "")
    if forwarded_proto:
        base_url = base_url.replace("http://", f"{forwarded_proto}://", 1)
    return base_url


def project_pdf_media_url(document: dict[str, Any], request: Request) -> dict[str, Any]:
    """Attach the existing local-media or Papers proxy URL to a document."""
    local_path = document.get("local_pdf_path") or ""
    base_url = public_base_url(request)
    if local_path:
        filename = os.path.basename(local_path)
        document["pdf_media_url"] = f"{base_url}/api/media/papers/{filename}"
    elif document.get("source") == "arxiv" and document.get("id"):
        document["pdf_media_url"] = f"{base_url}/api/papers/{document['id']}/pdf"
    else:
        document["pdf_media_url"] = None
    return document


def local_pdf_redirect_url(local_path: str, request: Request) -> str:
    return f"{public_base_url(request)}/api/media/papers/{os.path.basename(local_path)}"
