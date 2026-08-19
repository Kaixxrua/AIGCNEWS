"""支付订单状态机（ADR 0002）。

状态值写库前经本模块收口；库层不加 CHECK（迁移 0051 注释先例）。
唯一反直觉边是 expired → paid（迟到支付：我们已超时关单、渠道仍完成
扣款——钱已收就必须发权益，仅回调路径放行）；closed 是吸态，人工介入。
"""

from __future__ import annotations

ORDER_STATUS_PENDING = "pending"
ORDER_STATUS_PAID = "paid"
ORDER_STATUS_EXPIRED = "expired"
ORDER_STATUS_CLOSED = "closed"

ORDER_STATUSES: frozenset[str] = frozenset(
    {
        ORDER_STATUS_PENDING,
        ORDER_STATUS_PAID,
        ORDER_STATUS_EXPIRED,
        ORDER_STATUS_CLOSED,
    }
)

ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    ORDER_STATUS_PENDING: frozenset(
        {ORDER_STATUS_PAID, ORDER_STATUS_EXPIRED, ORDER_STATUS_CLOSED}
    ),
    # 迟到支付：仅回调/补单路径显式放行
    ORDER_STATUS_EXPIRED: frozenset({ORDER_STATUS_PAID}),
    ORDER_STATUS_PAID: frozenset(),
    ORDER_STATUS_CLOSED: frozenset(),
}

# 可转入 paid 的来源状态：仓储条件更新的 WHERE 子句与之一致
PAYABLE_STATUSES: frozenset[str] = frozenset(
    {ORDER_STATUS_PENDING, ORDER_STATUS_EXPIRED}
)


class InvalidOrderTransition(RuntimeError):
    """非法状态迁移：服务层防御性断言，正常路径不应触发。"""

    def __init__(self, old: str, new: str) -> None:
        super().__init__(f"invalid order transition: {old!r} -> {new!r}")
        self.old = old
        self.new = new


def normalize_order_status(value: object) -> str:
    """fail-closed 归一：未知状态按 closed 处理（最保守的不可支付展示态）。

    库内写路径只会写 ORDER_STATUSES 常量；本函数只用于读取侧防御脏数据。
    """
    if isinstance(value, str) and value in ORDER_STATUSES:
        return value
    return ORDER_STATUS_CLOSED


def assert_transition(old: str, new: str) -> None:
    """断言迁移合法；非法抛 InvalidOrderTransition。"""
    if new not in ALLOWED_TRANSITIONS.get(old, frozenset()):
        raise InvalidOrderTransition(old, new)
