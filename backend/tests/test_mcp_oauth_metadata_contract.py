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


MCP_GO = Path(__file__).resolve().parents[2] / "mcp-go"


def test_go_oauth_entry_challenge_points_at_the_published_metadata() -> None:
    # Go 的 /api/mcp/oauth 回 401 时把客户端指向这份资源元数据（RFC 9728 §5.1）；
    # 地址由资源路径推出，Go 侧 TestOAuthResourceMetadataMatchesPublishedFile 反向读同一份文件
    resource_path = urlsplit(MCP_OAUTH_RESOURCE).path
    metadata_url = f"{MCP_OAUTH_ISSUER}/.well-known/oauth-protected-resource{resource_path}"
    oauth_go = (MCP_GO / "internal" / "mcpapp" / "oauth.go").read_text(encoding="utf-8")
    assert f'const OAuthResourceMetadataURL = "{metadata_url}"' in oauth_go
    assert PROTECTED_RESOURCE.is_file()


def test_oauth_entry_is_routed_to_the_go_gateway() -> None:
    # 资源地址的路径要一路接到 Go：前端 nginx 精确转发、Go 路由挂载、main 接线，缺一处就回落
    # Python 主后端 404，客户端拿不到质询
    resource_path = urlsplit(MCP_OAUTH_RESOURCE).path
    nginx = (FRONTEND / "nginx.conf").read_text(encoding="utf-8")
    block = re.search(rf"\n    location = {re.escape(resource_path)} \{{\n(.*?)\n    \}}\n", nginx, re.S)
    assert block, resource_path
    assert "proxy_pass $mcp_go_upstream$request_uri;" in block.group(1)
    probes = (MCP_GO / "internal" / "probes" / "probes.go").read_text(encoding="utf-8")
    assert f'case "{resource_path}":' in probes
    main = (MCP_GO / "cmd" / "mcp-server" / "main.go").read_text(encoding="utf-8")
    assert "mcpHandler.OAuthEntry(mcpapp.OAuthResourceMetadataURL)" in main


def test_mcp_page_points_clients_at_the_oauth_resource() -> None:
    # /mcp 接入页的浏览器授权命令连这个地址。客户端按 RFC 9728 核对元数据里的 resource 与所连地址一致，
    # 授权请求带的 resource 也必须等于后端的 MCP_OAUTH_RESOURCE；差一个字符，登录就走不通
    source = (FRONTEND / "src" / "features" / "mcp" / "mcpOAuth.ts").read_text(encoding="utf-8")
    assert f"export const MCP_OAUTH_ENDPOINT = '{MCP_OAUTH_RESOURCE}'" in source
