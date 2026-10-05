"""会员试用规则的服务层入口；纯逻辑在 ``backend.app.domain.membership_trial``。

仓储层不得依赖服务层（test_layer_boundaries），试用的快照类型与状态口径
归属 domain/，这里原样转出，供路由与服务层使用。
"""

from __future__ import annotations

from backend.app.domain.membership_trial import (
    TRIAL_DAYS,
    TrialRecord,
    TrialSnapshot,
    is_effective_member,
    trial_expiry,
    trial_status,
)

__all__ = [
    "TRIAL_DAYS",
    "TrialRecord",
    "TrialSnapshot",
    "is_effective_member",
    "trial_expiry",
    "trial_status",
]
