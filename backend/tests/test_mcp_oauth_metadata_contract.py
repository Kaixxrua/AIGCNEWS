"""前端静态发布的 MCP OAuth 元数据（RFC 8414 / RFC 9728）必须与后端授权服务一致。

两份文件放在 frontend/public/.well-known/ 下，随前端发布包上两个边缘；客户端按它们找到
注册、授权、换令牌的地址，写错一处整个登录就走不通，所以逐字段钉住。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlsplit

from backend.app.api.routes_auth import MCP_TOKEN_SCOPES
from backend.app.services.auth.mcp_oauth import (
    MCP_OAUTH_ISSUER,
    MCP_OAUTH_RESOURCE,
    TOKEN_ENDPOINT_AUTH_METHODS,
)

FRONTEND = Path(__file__).resolve().parents[2] / "frontend"
WELL_KNOWN = FRONTEND / "public" / ".well-known"
AUTHORIZATION_SERVER = WELL_KNOWN / "oauth-authorization-server"
# RFC 9728 §3.1：资源地址带路径时，元数据地址是把 /.well-known/oauth-protected-resource 插在路径前面
PROTECTED_RESOURCE = WELL_KNOWN / "oauth-protected-resource" / urlsplit(MCP_OAUTH_RESOURCE).path.lstrip("/")


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_authorization_server_metadata_matches_the_backend() -> None:
    assert _load(AUTHORIZATION_SERVER) == {
        "issuer": MCP_OAUTH_ISSUER,
        "authorization_endpoint": f"{MCP_OAUTH_ISSUER}/oauth/authorize",
        "token_endpoint": f"{MCP_OAUTH_ISSUER}/api/oauth/token",
        "registration_endpoint": f"{MCP_OAUTH_ISSUER}/api/oauth/register",
        "scopes_supported": sorted(MCP_TOKEN_SCOPES),
        "response_types_supported": ["code"],
        "response_modes_supported": ["query"],
        "grant_types_supported": ["authorization_code"],
        "token_endpoint_auth_methods_supported": list(TOKEN_ENDPOINT_AUTH_METHODS),
        "code_challenge_methods_supported": ["S256"],
        "authorization_response_iss_parameter_supported": True,
        "service_documentation": f"{MCP_OAUTH_ISSUER}/mcp",
    }


def test_protected_resource_metadata_matches_the_backend() -> None:
    assert _load(PROTECTED_RESOURCE) == {
        "resource": MCP_OAUTH_RESOURCE,
        "authorization_servers": [MCP_OAUTH_ISSUER],
        "scopes_supported": sorted(MCP_TOKEN_SCOPES),
        "bearer_methods_supported": ["header"],
        "resource_name": "AIGC Radar MCP",
        "resource_documentation": f"{MCP_OAUTH_ISSUER}/mcp",
    }


def test_root_protected_resource_metadata_is_not_published() -> None:
    # 只给 /api/mcp/oauth 发资源元数据：根路径那份会让连 /api/mcp（匿名可用）的客户端也去走登录
    assert not (WELL_KNOWN / "oauth-protected-resource").is_file()
    assert sorted(path.relative_to(WELL_KNOWN).as_posix() for path in WELL_KNOWN.rglob("*") if path.is_file()) == [
        "oauth-authorization-server",
        "oauth-protected-resource/api/mcp/oauth",
    ]


def test_backend_endpoints_in_the_metadata_are_mounted() -> None:
    from backend.app.main import app

    paths = app.openapi()["paths"]
    metadata = _load(AUTHORIZATION_SERVER)
    for field in ("token_endpoint", "registration_endpoint"):
        assert "post" in paths[urlsplit(metadata[field]).path], field


def test_authorization_endpoint_is_a_frontend_page_the_edges_serve() -> None:
    path = urlsplit(_load(AUTHORIZATION_SERVER)["authorization_endpoint"]).path
    router = (FRONTEND / "src" / "router" / "index.ts").read_text(encoding="utf-8")
    assert re.search(rf"path: '{re.escape(path)}'", router)
    # 边缘只给 __routes 清单里的首段返回 200，清单外一律 404
    assert (FRONTEND / "public" / "__routes" / path.split("/")[1]).is_file()
