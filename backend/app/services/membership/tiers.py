"""会员档位常量与归一化。

档位的库内权威值只有两个：free / member。所有外部输入（API body、库内
脏数据、缺列回退）都经 ``normalize_membership_tier`` 收口，未知值一律
按 free 处理——fail-closed，宁可少给权益也不误发会员权益。

到期语义（0048）：``membership_expires_at`` 为 NULL 表示长期有效；非空
且已过期时，生效档位按 free 处理。读取侧（RequireUser、MCP token、会员
feed）统一经 ``resolve_effective_tier`` 收口，库内档位列不回写。
"""

from __future__ import annotations

from backend.app.domain.membership import (
    DEFAULT_MEMBERSHIP_TIER,
    MEMBERSHIP_TIER_FREE,
    MEMBERSHIP_TIER_MEMBER,
    MEMBERSHIP_TIERS,
    normalize_membership_tier,
    resolve_effective_tier,
)

__all__ = [
    "DEFAULT_MEMBERSHIP_TIER",
    "MEMBERSHIP_TIER_FREE",
    "MEMBERSHIP_TIER_MEMBER",
    "MEMBERSHIP_TIERS",
    "normalize_membership_tier",
    "resolve_effective_tier",
]
