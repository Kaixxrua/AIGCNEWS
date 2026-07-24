from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

import httpx
import pytest

from backend.app.services import mcp_connection_tester as tester

PUBLIC_IP = "8.8.8.8"


def _resolver(_hostname: str) -> Iterable[str]:
    return [PUBLIC_IP]


def _config(**overrides: Any) -> dict[str, Any]:
    config = {
        "url": "https://mcp.example:8443/rpc",
        "transport": "streamable_http",
        "auth_type": "bearer",
        "auth_token": "top-secret-token",
    }
    config.update(overrides)
    return config


def _client_factory(handler: Any, captured: dict[str, Any]):
    def factory(**kwargs: Any) -> httpx.Client:
        captured["client_kwargs"] = kwargs
        return httpx.Client(transport=httpx.MockTransport(handler), **kwargs)

    return factory


def test_initialize_notification_tools_list_and_session_headers() -> None:
    requests: list[httpx.Request] = []
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        payload = json.loads(request.content)
        assert request.url.host == PUBLIC_IP
        assert request.url.port == 8443
        assert request.headers["host"] == "mcp.example:8443"
        assert request.extensions["sni_hostname"] == "mcp.example"
        assert request.headers["authorization"] == "Bearer top-secret-token"
        if payload["method"] == "initialize":
            assert request.headers["mcp-protocol-version"] == tester.MCP_PROTOCOL_VERSION
            return httpx.Response(
                200,
                headers={"Mcp-Session-Id": "session-123"},
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "result": {"protocolVersion": "2024-11-05"},
                },
            )
        assert request.headers["mcp-session-id"] == "session-123"
        assert request.headers["mcp-protocol-version"] == "2024-11-05"
        if payload["method"] == "notifications/initialized":
            assert "id" not in payload
            return httpx.Response(204)
        assert payload["method"] == "tools/list"
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "result": {"tools": [{"name": "search", "description": "Search only"}]},
            },
        )

    result = tester.test_mcp_server_connection(
        _config(), resolver=_resolver, client_factory=_client_factory(handler, captured)
    )

    assert result == {
        "status": "success",
        "message": "连接成功，发现 1 个工具。",
        "tools": [{"name": "search", "description": "Search only"}],
    }
    assert [json.loads(request.content)["method"] for request in requests] == [
        "initialize",
        "notifications/initialized",
        "tools/list",
    ]
    assert captured["client_kwargs"]["follow_redirects"] is False
    assert captured["client_kwargs"]["trust_env"] is False


def test_json_and_sse_responses_are_decoded() -> None:
    seen = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal seen
        seen += 1
        if seen == 1:
            return httpx.Response(
                200,
                json={"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": "2025-06-18"}},
            )
        if seen == 2:
            return httpx.Response(202)
        return httpx.Response(
            200,
            headers={"Content-Type": "text/event-stream"},
            content=(
                b": keepalive\n\n"
                b"data: {\"jsonrpc\":\"2.0\",\"method\":\"notifications/progress\"}\n\n"
                b"data: {\"jsonrpc\":\"2.0\",\"id\":2,\"result\":{\"tools\":[]}}\n\n"
            ),
        )

    result = tester.test_mcp_server_connection(
        _config(), resolver=_resolver, client_factory=_client_factory(handler, {})
    )
    assert result == {"status": "success", "message": "连接成功。", "tools": []}


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.com/rpc",
        "https://user:pass@example.com/rpc",
        "https://example.com:99999/rpc",
        "https://127.0.0.1/rpc",
        "https://[::1]/rpc",
        "https://169.254.169.254/latest/meta-data",
        "https://metadata.google.internal/rpc",
        "https://localhost/rpc",
    ],
)
def test_bad_schemes_userinfo_ports_and_literal_targets_are_rejected(url: str) -> None:
    result = tester.test_mcp_server_connection(_config(url=url), resolver=_resolver)
    assert result["status"] == "failed"


@pytest.mark.parametrize("answer", ["10.0.0.1", "127.0.0.1", "169.254.1.1", "224.0.0.1", "0.0.0.0", "192.0.2.1"])
def test_private_loopback_link_local_metadata_and_reserved_dns_are_rejected(answer: str) -> None:
    result = tester.test_mcp_server_connection(
        _config(), resolver=lambda _hostname: [answer]
    )
    assert result == {
        "status": "failed",
        "message": "不允许访问本地、内网或保留地址",
        "tools": [],
    }


def test_mixed_public_private_dns_is_rejected() -> None:
    result = tester.test_mcp_server_connection(
        _config(), resolver=lambda _hostname: [PUBLIC_IP, "10.0.0.1"]
    )
    assert result["status"] == "failed"
    assert "不允许访问" in result["message"]


def test_target_is_resolved_once_and_pinned_for_complete_sequence() -> None:
    resolutions = 0
    request_hosts: list[str] = []

    def resolver(_hostname: str) -> Iterable[str]:
        nonlocal resolutions
        resolutions += 1
        return [PUBLIC_IP] if resolutions == 1 else ["127.0.0.1"]

    def handler(request: httpx.Request) -> httpx.Response:
        request_hosts.append(request.url.host or "")
        payload = json.loads(request.content)
        if payload["method"] == "initialize":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {}})
        if payload["method"] == "notifications/initialized":
            return httpx.Response(204)
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 2, "result": {"tools": []}})

    result = tester.test_mcp_server_connection(
        _config(), resolver=resolver, client_factory=_client_factory(handler, {})
    )
    assert result["status"] == "success"
    assert resolutions == 1
    assert request_hosts == [PUBLIC_IP, PUBLIC_IP, PUBLIC_IP]


def test_redirect_is_not_followed() -> None:
    requests = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(302, headers={"Location": "http://127.0.0.1/admin"})

    result = tester.test_mcp_server_connection(
        _config(), resolver=_resolver, client_factory=_client_factory(handler, {})
    )
    assert result["status"] == "failed"
    assert "HTTP 302" in result["message"]
    assert requests == 1


def test_oversized_json_and_sse_responses_are_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tester, "MAX_RESPONSE_BYTES", 64)

    for content_type, body in [
        ("application/json", b"{" + b" " * 100 + b"}"),
        ("text/event-stream", b"data: " + b"x" * 100 + b"\n\n"),
    ]:
        def handler(request: httpx.Request, *, body: bytes = body, content_type: str = content_type) -> httpx.Response:
            return httpx.Response(200, headers={"Content-Type": content_type}, content=body)

        result = tester.test_mcp_server_connection(
            _config(), resolver=_resolver, client_factory=_client_factory(handler, {})
        )
        assert result["status"] == "failed"
        assert "响应过大" in result["message"]


def test_token_is_redacted_from_transport_errors() -> None:
    token = "token-never-leaks"

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"failed with {token}", request=request)

    result = tester.test_mcp_server_connection(
        _config(auth_token=token), resolver=_resolver, client_factory=_client_factory(handler, {})
    )
    assert result["status"] == "failed"
    assert token not in result["message"]
    assert "****" in result["message"]


def test_only_streamable_http_is_supported_without_network() -> None:
    called = False

    def resolver(_hostname: str) -> Iterable[str]:
        nonlocal called
        called = True
        return [PUBLIC_IP]

    result = tester.test_mcp_server_connection(_config(transport="sse"), resolver=resolver)
    assert result["status"] == "failed"
    assert called is False


def test_tester_never_executes_discovered_tools() -> None:
    methods: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        methods.append(payload["method"])
        if payload["method"] == "initialize":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {}})
        if payload["method"] == "notifications/initialized":
            return httpx.Response(204)
        return httpx.Response(
            200,
            json={"jsonrpc": "2.0", "id": 2, "result": {"tools": [{"name": "dangerous"}]}},
        )

    result = tester.test_mcp_server_connection(
        _config(), resolver=_resolver, client_factory=_client_factory(handler, {})
    )
    assert result["status"] == "success"
    assert methods == ["initialize", "notifications/initialized", "tools/list"]
    assert "tools/call" not in methods
