from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.app.domain.membership import resolve_access_tier


@dataclass(frozen=True)
class McpAuthorizationContext:
    """MCP token 身份与 scope 的有界视图。

    入站协议分发/会话传输已随 W6-U4 退役（生产 /api/mcp 由 mcp-go 服务）；
    本类型仍被 REST 侧 routes_projects_api 复用做 token 身份投影。
    """

    user: dict[str, Any] | None

    @property
    def is_authenticated(self) -> bool:
        return self.user is not None

    @property
    def user_id(self) -> int:
        try:
            return int((self.user or {}).get("user_id") or 0)
        except (TypeError, ValueError):
            return 0

    @property
    def role(self) -> str:
        """库内角色（MCP token JOIN 已带列）；匿名或缺列按 user。"""

        return str((self.user or {}).get("role") or "user")

    @property
    def membership_tier(self) -> str:
        """Every authenticated account has the same access; anonymous stays free."""
        return resolve_access_tier(self.user)

    def has_scope(self, scope: str) -> bool:
        return scope in (self.user or {}).get("scopes", frozenset())
