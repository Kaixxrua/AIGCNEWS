"""公开特性开关端点：前端据此隐藏被关闭源的视图、导航与入口。

只读、无需鉴权；每次请求实时读取 settings，测试可经单例翻转。
"""

from __future__ import annotations

from fastapi import APIRouter

from backend.app.core.config import settings

router = APIRouter()


@router.get("/features")
async def get_features() -> dict[str, bool]:
    """返回可插拔采集源开关状态。"""
    return {
        "x_source": bool(settings.x_source_enabled),
        "wechat_source": bool(settings.wechat_source_enabled),
    }
