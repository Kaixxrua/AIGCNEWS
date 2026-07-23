from __future__ import annotations

from typing import Any, Protocol


class McpServerConfigSeeder(Protocol):
    """Initialize editable MCP Server rows from configured defaults."""

    def _seed_default_mcp_server_configs(self) -> None: ...


class McpServerConfigReader(Protocol):
    """Read internal MCP Server rows, which may contain ``auth_token``."""

    def list_mcp_server_configs(self) -> list[dict[str, Any]]: ...

    def get_mcp_server_config(
        self,
        server_id: int,
    ) -> dict[str, Any] | None: ...


class McpServerConfigWriter(Protocol):
    """Create, update, and delete MCP Server configurations."""

    def create_mcp_server_config(
        self,
        payload: dict[str, Any],
    ) -> dict[str, Any]: ...

    def update_mcp_server_config(
        self,
        server_id: int,
        payload: dict[str, Any],
    ) -> dict[str, Any] | None: ...

    def delete_mcp_server_config(self, server_id: int) -> bool: ...


class McpServerTestResultWriter(Protocol):
    """Persist the latest MCP Server connectivity result."""

    def update_mcp_server_test_result(
        self,
        server_id: int,
        result: dict[str, Any],
    ) -> dict[str, Any] | None: ...


class McpServerConfigRepository(
    McpServerConfigSeeder,
    McpServerConfigReader,
    McpServerConfigWriter,
    McpServerTestResultWriter,
    Protocol,
):
    """Internal persistence boundary; API presenters must redact secrets."""
