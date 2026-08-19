"""会员档位常量与归一化。

档位的库内权威值只有两个：free / member。所有外部输入（API body、库内
脏数据、缺列回退）都经 ``normalize_membership_tier`` 收口，未知值一律
按 free 处理——fail-closed，宁可少给权益也不误发会员权益。

到期语义（0048）：``membership_expires_at`` 为 NULL 表示长期有效；非空
且已过期时，生效档位按 free 处理。读取侧（RequireUser、MCP token、会员
feed）统一经 ``resolve_effective_tier`` 收口，库内档位列不回写。
"""

from __future__ import annotations

from datetime import datetime, timezone

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


def _coerce_expires_at(value: object) -> datetime | None:
    """把库内 datetime / ISO 串归一为带时区 datetime；无法解析按无到期处理。

    psycopg 读 TIMESTAMPTZ 已返回 aware datetime；测试替身与 JSON 链路
    可能给 ISO 串。naive datetime 按 UTC 解释（与库内 timestamptz 口径一致）。
    解析失败回退 None（长期有效）属于 fail-open，但仅限脏数据场景；
    档位本身仍由 normalize_membership_tier fail-closed 兜底。
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        expiry = value
    elif isinstance(value, str):
        try:
            expiry = datetime.fromisoformat(value.strip())
        except ValueError:
            return None
    else:
        return None
    if expiry.tzinfo is None:
        return expiry.replace(tzinfo=timezone.utc)
    return expiry


def resolve_effective_tier(
    value: object,
    expires_at: object = None,
    *,
    now: datetime | None = None,
) -> str:
    """库内档位 + 到期时间 → 当前生效档位；member 已过期按 free。"""
    tier = normalize_membership_tier(value)
    if tier != MEMBERSHIP_TIER_MEMBER:
        return tier
    expiry = _coerce_expires_at(expires_at)
    if expiry is None:
        return tier
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return MEMBERSHIP_TIER_FREE if expiry <= current else tier
