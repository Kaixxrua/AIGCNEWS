"""公开特性开关端点：前端据此隐藏被关闭源的视图、导航与入口。

只读、无需鉴权；每次请求实时读取 settings，测试可经单例翻转。
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from backend.app.core.config import settings
from backend.app.services.auth.oauth.registry import configured_oauth_providers
from backend.app.services.auth.oauth.runtime_config import resolve_oauth_config
from backend.app.services.push.telegram_config_provider import resolve_telegram_config

router = APIRouter()


@router.get("/features")
async def get_features(request: Request) -> dict[str, object]:
    """返回可插拔采集源和真实可用的 OAuth provider 状态。"""
    config = resolve_oauth_config()
    return {
        "x_source": bool(settings.x_source_enabled),
        "wechat_source": bool(settings.wechat_source_enabled),
        "oauth_providers": configured_oauth_providers(
            redis_available=getattr(request.app.state, "redis", None) is not None,
            config=config,
        ),
        # Telegram 推送开关：DB 行覆盖 env（60s TTL），前端据此显隐订阅页卡片。
        "telegram_push_enabled": bool(resolve_telegram_config().enabled),
    }
