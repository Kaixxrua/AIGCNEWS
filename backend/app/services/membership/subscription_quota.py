"""简报订阅档位配额：免费档 1 个日报模块，会员全部 8 模块。

跨体系合计防绕过：体系 A ``briefing_subscriptions``（/report/subscribe*）
与体系 B ``user_subscriptions``（/push/me/subscriptions*，frequency 仅
daily）共享同一源词汇表，只校验一边会被「A 订 1 个 + B 订 8 个」绕过；
同一 source 跨体系重复只算一个模块——档位约束的是「能收到几个模块的
日报」，而非订阅记录条数。

存量豁免（grandfather）：只约束新增/恢复，存量超档订阅继续派发；
已活跃 source 的重复 upsert 幂等放行，不视为新增模块。
"""

from __future__ import annotations

from typing import Any, Protocol

from backend.app.services.membership.tiers import (
    MEMBERSHIP_TIER_MEMBER,
    normalize_membership_tier,
)

FREE_TIER_DAILY_SUBSCRIPTION_LIMIT = 1

SUBSCRIPTION_QUOTA_EXCEEDED_DETAIL = (
    "免费档最多订阅 1 个日报模块，开通会员解锁全部 8 个模块"
)


class SubscriptionQuotaExceededError(Exception):
    """订阅模块数超档位上限（路由层映射 403）。"""

    def __init__(self, detail: str = SUBSCRIPTION_QUOTA_EXCEEDED_DETAIL) -> None:
        super().__init__(detail)
        self.detail = detail


class BriefingSubscriptionSourceReader(Protocol):
    """体系 A 读边界：只回该用户活跃日报订阅行。"""

    def get_user_briefing_subscriptions(
        self, user_id: int
    ) -> list[dict[str, Any]]: ...


class UserSubscriptionSourceReader(Protocol):
    """体系 B 读边界：回该用户全部订阅行（含 paused），调用方过滤。"""

    def list_subscriptions(self, user_id: int) -> list[dict[str, Any]]: ...


def collect_active_daily_sources(
    *,
    briefing_subscriptions: BriefingSubscriptionSourceReader,
    user_subscriptions: UserSubscriptionSourceReader,
    user_id: int,
) -> set[str]:
    """跨体系 A+B 合计活跃日报模块（按 source 去重）。

    体系 B 只统计 status == "active" 的行（frequency 仅有 daily，
    缺省防御性按 daily 处理）；体系 A 读接口本身只回活跃日报。
    """

    sources = {
        str(row["source"])
        for row in briefing_subscriptions.get_user_briefing_subscriptions(user_id)
        if row.get("source")
    }
    sources.update(
        str(row["source"])
        for row in user_subscriptions.list_subscriptions(user_id)
        if row.get("source")
        and row.get("status") == "active"
        and row.get("frequency", "daily") == "daily"
    )
    return sources


def ensure_subscription_quota(
    *,
    tier: str,
    active_sources: set[str],
    adding_sources: set[str],
) -> None:
    """member 放行；free 档新增模块使合计超上限时抛 SubscriptionQuotaExceededError。

    adding 中已活跃的 source（重复 upsert / 对同 source 已活跃渠道的变更）
    不计新增——存量豁免语义：超档存量继续可用，但任何新模块都被拒绝。
    """

    if normalize_membership_tier(tier) == MEMBERSHIP_TIER_MEMBER:
        return
    effective_new = set(adding_sources) - set(active_sources)
    if not effective_new:
        return
    if len(set(active_sources) | effective_new) > FREE_TIER_DAILY_SUBSCRIPTION_LIMIT:
        raise SubscriptionQuotaExceededError()
