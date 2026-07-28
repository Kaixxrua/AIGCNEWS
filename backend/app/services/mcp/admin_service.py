from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol


class McpConfigStore(Protocol):
    def get_mcp_server_config(self, server_id: int) -> Mapping[str, Any] | None: ...

    def update_mcp_server_test_result(
        self,
        server_id: int,
        result: Mapping[str, Any],
    ) -> Mapping[str, Any] | None: ...


@dataclass(frozen=True, slots=True)
class SafeMcpServerProjection:
    id: int
    server_key: str
    display_name: str
    description: str
    url: str
    transport: str
    auth_type: str
    auth_token_configured: bool
    auth_token_masked: str | None
    enabled: bool
    last_test_status: str
    last_test_message: str
    tools: tuple[dict[str, str], ...]
    last_test_at: str | None
    created_at: str | None
    updated_at: str | None


def mask_token(token: str | None) -> str | None:
    if not token:
        return None
    if len(token) <= 8:
        return "****"
    return f"{token[:4]}****{token[-4:]}"


def project_server(
    row: Mapping[str, Any],
    *,
    tools: tuple[dict[str, str], ...] = (),
) -> SafeMcpServerProjection:
    token = str(row.get("auth_token") or "")
    return SafeMcpServerProjection(
        id=int(row.get("id") or 0),
        server_key=str(row.get("server_key") or ""),
        display_name=str(row.get("display_name") or ""),
        description=str(row.get("description") or ""),
        url=str(row.get("url") or ""),
        transport=str(row.get("transport") or "streamable_http"),
        auth_type=str(row.get("auth_type") or "none"),
        auth_token_configured=bool(token),
        auth_token_masked=mask_token(token),
        enabled=bool(row.get("enabled")),
        last_test_status=str(row.get("last_test_status") or "unknown"),
        last_test_message=str(row.get("last_test_message") or ""),
        tools=tools,
        last_test_at=_optional_string(row.get("last_test_at")),
        created_at=_optional_string(row.get("created_at")),
        updated_at=_optional_string(row.get("updated_at")),
    )


def _optional_string(value: Any) -> str | None:
    return str(value) if value is not None else None


@dataclass(frozen=True, slots=True)
class ConnectionTestOutcome:
    result: dict[str, Any]
    server: Mapping[str, Any]


class McpAdminService:
    def __init__(self, store: McpConfigStore) -> None:
        self._store = store

    def test_connection(
        self,
        server_id: int,
        tester,
    ) -> ConnectionTestOutcome | None:
        row = self._store.get_mcp_server_config(server_id)
        if row is None:
            return None
        result = tester(dict(row))
        updated = self._store.update_mcp_server_test_result(server_id, result)
        return ConnectionTestOutcome(result=dict(result), server=updated or row)
