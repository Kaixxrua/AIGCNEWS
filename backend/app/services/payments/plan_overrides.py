"""Runtime plan price overrides: DB rows merged over plans.py defaults with a short TTL cache."""

from __future__ import annotations

import logging
import threading
import time

from backend.app.repositories.payment_plan_overrides_repository import PaymentPlanOverridesReader
from backend.app.services.payments.plans import (
    MEMBERSHIP_PLANS,
    MembershipPlan,
    UnknownPlanError,
    effective_plans,
)

logger = logging.getLogger(__name__)
_CACHE_TTL_SECONDS = 60.0

_reader: PaymentPlanOverridesReader | None = None
_cache: tuple[float, dict[str, MembershipPlan]] | None = None
_lock = threading.Lock()


def configure_plan_overrides_reader(reader: PaymentPlanOverridesReader | None) -> None:
    global _reader, _cache
    with _lock:
        _reader, _cache = reader, None


def invalidate_plan_overrides_cache() -> None:
    global _cache
    with _lock:
        _cache = None


def reset_plan_overrides_provider() -> None:
    configure_plan_overrides_reader(None)


def resolve_effective_plans() -> dict[str, MembershipPlan]:
    """生效套餐目录：默认价 + DB 覆盖；读失败降级纯默认价（宁可按原价也不 500）。"""
    global _cache
    with _lock:
        if _cache is not None and time.monotonic() - _cache[0] < _CACHE_TTL_SECONDS:
            return dict(_cache[1])
        plans = dict(MEMBERSHIP_PLANS)
        if _reader is not None:
            try:
                rows = _reader.list_plan_overrides()
            except Exception:
                logger.warning("[Payments] 读取 payment_plan_overrides 失败，按默认价生效", exc_info=True)
            else:
                plans = effective_plans({row.plan_code: row.amount_cents for row in rows})
                _cache = (time.monotonic(), plans)
        return dict(plans)


def get_effective_plan(code: object) -> MembershipPlan:
    """按码取生效套餐；未知码抛 UnknownPlanError（fail-closed，与 get_plan 同语义）。"""
    plan = resolve_effective_plans().get(code) if isinstance(code, str) else None
    if plan is None:
        raise UnknownPlanError(code)
    return plan
