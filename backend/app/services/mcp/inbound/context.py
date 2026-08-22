from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.app.services.membership.tiers import resolve_effective_tier


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
        """库内生效会员档位（0045/0048）；匿名或缺列按 free，过期 member 回落 free。"""

        user = self.user or {}
        return resolve_effective_tier(
            user.get("membership_tier"),
            user.get("membership_expires_at"),
        )

    def has_scope(self, scope: str) -> bool:
        return scope in (self.user or {}).get("scopes", frozenset())
