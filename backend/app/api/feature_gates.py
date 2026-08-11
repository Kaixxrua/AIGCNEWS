"""可插拔采集源路由门控依赖：特性开关关闭时整组路由 404。

以请求时读取 settings 的方式判定（而非启动期条件挂载），对外语义与
未部署该源一致（404），同时保证测试可经 settings 单例翻转两个方向。
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


def require_wechat_source_enabled() -> None:
    """微信公众号源关闭时 404（对外与未部署该源一致）。"""
    from backend.app.core.config import settings

    if not settings.wechat_source_enabled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="wechat_source_disabled",
        )
