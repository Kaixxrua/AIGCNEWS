"""会员档位常量与归一化。

档位的库内权威值只有两个：free / member。所有外部输入（API body、库内
脏数据、缺列回退）都经 ``normalize_membership_tier`` 收口，未知值一律
按 free 处理——fail-closed，宁可少给权益也不误发会员权益。
"""

from __future__ import annotations

MEMBERSHIP_TIER_FREE = "free"
MEMBERSHIP_TIER_MEMBER = "member"

DEFAULT_MEMBERSHIP_TIER = MEMBERSHIP_TIER_FREE

MEMBERSHIP_TIERS: frozenset[str] = frozenset(
    {MEMBERSHIP_TIER_FREE, MEMBERSHIP_TIER_MEMBER}
)


def normalize_membership_tier(value: object) -> str:
    """把任意输入归一到合法档位；未知/空值一律回退 free。"""
    if isinstance(value, str) and value in MEMBERSHIP_TIERS:
        return value
    return DEFAULT_MEMBERSHIP_TIER
