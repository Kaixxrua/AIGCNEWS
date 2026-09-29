"""可插拔采集源路由门控依赖：特性开关关闭时整组路由 404。

以请求时读取 settings 的方式判定（而非启动期条件挂载），对外语义与
未部署该源一致（404），同时保证测试可经 settings 单例翻转开关。
"""

from __future__ import annotations

from fastapi import HTTPException, status


def require_x_source_enabled() -> None:
    """X 源关闭时 404（对外与未部署该源一致）。"""
    from backend.app.core.config import settings

    if not settings.x_source_enabled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="x_source_disabled",
        )


def require_payments_enabled() -> None:
    """支付骨架总开关关闭时 404（对外与未部署收费能力一致）。

    渠道凭证缺失不走到这里：开关开 + 渠道未配置由路由层映射 503
    payment_channel_not_configured（ADR 0002 的 404/503 双层语义）。
    """
    from backend.app.services.payments.runtime_config import resolve_payment_config

    if not resolve_payment_config().enabled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="payments_disabled",
        )
