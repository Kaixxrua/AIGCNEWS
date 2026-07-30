from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Protocol

from backend.app.repositories.mcp_server_repository import McpServerConfigConflictError
from backend.app.services.mcp_connection_tester import (
    McpConnectionTestError,
    validate_mcp_http_url,
)


class McpConfigStore(Protocol):
    def list_mcp_server_configs(self) -> list[dict[str, Any]]: ...

    def get_mcp_server_config(self, server_id: int) -> Mapping[str, Any] | None: ...

    def create_mcp_server_config(
        self,
        payload: dict[str, Any],
    ) -> Mapping[str, Any]: ...

    def update_mcp_server_config(
        self,
        server_id: int,
        payload: dict[str, Any],
    ) -> Mapping[str, Any] | None: ...

    def delete_mcp_server_config(self, server_id: int) -> bool: ...

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
    tools: tuple[dict[str, str], ...] | None = None,
) -> SafeMcpServerProjection:
    token = str(row.get("auth_token") or "")
    projected_tools = tools if tools is not None else parse_stored_tools(row.get("last_tools_json"))
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
        tools=projected_tools,
        last_test_at=_optional_string(row.get("last_test_at")),
        created_at=_optional_string(row.get("created_at")),
        updated_at=_optional_string(row.get("updated_at")),
    )


def parse_stored_tools(raw_value: Any) -> tuple[dict[str, str], ...]:
    if not raw_value:
        return ()
    if isinstance(raw_value, list):
        data = raw_value
    else:
        try:
            data = json.loads(str(raw_value))
        except (TypeError, json.JSONDecodeError):
            return ()
    if not isinstance(data, list):
        return ()
    tools = []
    for item in data:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if name:
            tools.append(
                {"name": name, "description": str(item.get("description") or "").strip()}
            )
    return tuple(tools)


def _optional_string(value: Any) -> str | None:
    return str(value) if value is not None else None


@dataclass(frozen=True, slots=True)
class ConnectionTestOutcome:
    result: dict[str, Any]
    server: Mapping[str, Any] | SafeMcpServerProjection


class McpAdminValidationError(ValueError):
    pass


class McpAdminNotFoundError(LookupError):
    pass


class McpAdminConflictError(RuntimeError):
    pass


McpConnectionTester = Callable[[dict[str, Any]], Mapping[str, Any]]


class McpAdminService:
    def __init__(
        self,
        store: McpConfigStore,
        tester: McpConnectionTester | None = None,
    ) -> None:
        self._store = store
        self._tester = tester

    async def list_servers(self) -> list[SafeMcpServerProjection]:
        rows = await asyncio.to_thread(self._store.list_mcp_server_configs)
        return [project_server(row) for row in rows]

    async def create_server(
        self,
        values: Mapping[str, Any],
    ) -> SafeMcpServerProjection:
        payload = normalize_server_payload(values)
        try:
            row = await asyncio.to_thread(
                self._store.create_mcp_server_config,
                payload,
            )
        except McpServerConfigConflictError as exc:
            raise McpAdminConflictError("server_key 已存在，请换一个标识") from exc
        return project_server(row)

    async def update_server(
        self,
        server_id: int,
        values: Mapping[str, Any],
    ) -> SafeMcpServerProjection:
        payload = normalize_server_payload(values)
        try:
            row = await asyncio.to_thread(
                self._store.update_mcp_server_config,
                server_id,
                payload,
            )
        except McpServerConfigConflictError as exc:
            raise McpAdminConflictError("server_key 已存在，请换一个标识") from exc
        if row is None:
            raise McpAdminNotFoundError("MCP Server 配置不存在")
        return project_server(row)

    async def delete_server(self, server_id: int) -> None:
        deleted = await asyncio.to_thread(
            self._store.delete_mcp_server_config,
            server_id,
        )
        if not deleted:
            raise McpAdminNotFoundError("MCP Server 配置不存在")

    async def test_server(self, server_id: int) -> ConnectionTestOutcome:
        if self._tester is None:
            raise RuntimeError("MCP connection tester is not configured")
        outcome = await asyncio.to_thread(
            self.test_connection,
            server_id,
            self._tester,
        )
        if outcome is None:
            raise McpAdminNotFoundError("MCP Server 配置不存在")
        return ConnectionTestOutcome(
            result=outcome.result,
            server=project_server(outcome.server),
        )

    def test_connection(
        self,
        server_id: int,
        tester: McpConnectionTester,
    ) -> ConnectionTestOutcome | None:
        row = self._store.get_mcp_server_config(server_id)
        if row is None:
            return None
        result = tester(dict(row))
        updated = self._store.update_mcp_server_test_result(server_id, result)
        return ConnectionTestOutcome(result=dict(result), server=updated or row)


def normalize_server_payload(values: Mapping[str, Any]) -> dict[str, Any]:
    server_key = str(values.get("server_key") or "").strip().lower()
    if not re.fullmatch(r"[a-z0-9_-]{2,64}", server_key):
        raise McpAdminValidationError(
            "server_key 仅支持 2-64 位小写字母、数字、下划线和短横线"
        )
    display_name = str(values.get("display_name") or "").strip()
    if not display_name:
        raise McpAdminValidationError("请填写 MCP Server 名称")
    try:
        url = validate_mcp_http_url(str(values.get("url") or ""))
    except McpConnectionTestError as exc:
        raise McpAdminValidationError(str(exc)) from exc
    return {
        "server_key": server_key,
        "display_name": display_name,
        "description": str(values.get("description") or "").strip(),
        "url": url,
        "transport": values.get("transport", "streamable_http"),
        "auth_type": values.get("auth_type", "none"),
        "auth_token": values.get("auth_token"),
        "clear_auth_token": bool(values.get("clear_auth_token", False)),
        "enabled": bool(values.get("enabled", True)),
    }
