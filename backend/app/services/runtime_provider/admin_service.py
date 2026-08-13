from __future__ import annotations

"""Administrative runtime model configuration commands."""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any, Mapping
from urllib.parse import urlparse

from backend.app.repositories.runtime_provider_repository import (
    RuntimeProviderSettingManager,
)
from backend.app.services.outbound_target_policy import (
    OutboundTargetPolicyError,
    normalize_http_url,
    resolve_public_ips,
)
from backend.app.services.runtime_provider.control_plane import (
    ENRICHMENT_REASONING_EFFORT_DEFAULT,
    RuntimeProviderUpdate,
    SafeProviderProjection,
    normalize_reasoning_effort,
    project_provider_config,
    resolve_enrichment_reasoning_effort,
)

logger = logging.getLogger(__name__)

# 连接测试的整体等待上限：真实请求一次模型，超时即判失败，不让面板空等
_TEST_TIMEOUT_SECONDS = 30.0


class InvalidProviderBaseUrl(ValueError):
    """运维页下发的 Base URL 未通过出站目标策略（SSRF 防护）。"""


def validate_admin_base_url(base_url: str) -> str:
    """空串 = 跟随 provider 官方默认；非空必须解析为指向公网的 http/https URL。

    渗透实测：运维面板可写入任意 Base URL，之后的模型调用（聊天/富化/
    连接测试）即成为服务端内网请求原语，可探测云元数据与内网服务。
    保存前与连接测试前统一校验；返回规范化后的 URL。
    """
    if not base_url:
        return ""
    try:
        url = normalize_http_url(base_url)
        resolve_public_ips(urlparse(url).hostname or "")
    except OutboundTargetPolicyError as exc:
        raise InvalidProviderBaseUrl(f"Base URL 不合法：{exc}") from exc
    return url


def _classify_test_failure(exc: Exception) -> str:
    """按异常类型给出分类排查文案（不回显异常原文，防泄露内部细节）。"""
    name = type(exc).__name__.lower()
    if any(marker in name for marker in ("auth", "permission", "forbidden")):
        return "鉴权失败，请检查 API Key 是否正确"
    if any(marker in name for marker in ("connect", "resolve", "proxy", "ssl", "tls")):
        return "网络连接失败，请检查 Base URL 与网络代理"
    if any(marker in name for marker in ("notfound", "not_found", "missing")):
        return "模型或接口不存在，请检查模型名称与 Base URL"
    if "rate" in name and "limit" in name:
        return "触发上游限流，请稍后重试"
    return "请求失败，请检查模型服务配置与网络环境"


class RuntimeProviderAdminService:
    def __init__(
        self,
        settings: RuntimeProviderSettingManager,
        *,
        invalidate_models: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self._settings = settings
        self._invalidate_models = invalidate_models

    async def get_config(self) -> SafeProviderProjection:
        row = await asyncio.to_thread(self._settings.get_runtime_provider_setting)
        return project_provider_config(row, fallback_provider="openai")

    async def update_config(
        self,
        values: Mapping[str, Any],
    ) -> SafeProviderProjection:
        update = RuntimeProviderUpdate.from_values(
            provider=str(values.get("provider") or ""),
            base_url=validate_admin_base_url(str(values.get("base_url") or "")),
            api_key=values.get("api_key"),
            clear_api_key=bool(values.get("clear_api_key", False)),
            model_name=str(values.get("model_name") or ""),
            reasoning_effort=str(values.get("reasoning_effort") or ""),
        )
        row = await asyncio.to_thread(
            self._settings.upsert_runtime_provider_setting,
            update.provider,
            update.base_url,
            values.get("api_key"),
            update.clear_api_key,
            update.model_name,
            update.reasoning_effort,
        )
        if self._invalidate_models is not None:
            await self._invalidate_models()
        return project_provider_config(row, fallback_provider=update.provider)

    @staticmethod
    def _enrichment_projection(row: Mapping[str, Any] | None) -> dict[str, str]:
        # reasoning_effort 为富化专用配置（空串=跟随模型服务配置）；
        # effective 与富化器读取链路同序：专用 > 模型服务 > medium 缺省
        return {
            "reasoning_effort": normalize_reasoning_effort(
                row.get("enrichment_reasoning_effort") if row else None
            ),
            "effective_reasoning_effort": resolve_enrichment_reasoning_effort(row)
            or ENRICHMENT_REASONING_EFFORT_DEFAULT,
        }

    async def get_enrichment_config(self) -> dict[str, str]:
        row = await asyncio.to_thread(self._settings.get_runtime_provider_setting)
        return self._enrichment_projection(row)

    async def update_enrichment_config(
        self,
        values: Mapping[str, Any],
    ) -> dict[str, str]:
        # 无需重建模型缓存：富化器以显式参数下发该值，缓存键随取值变化
        effort = normalize_reasoning_effort(str(values.get("reasoning_effort") or ""))
        row = await asyncio.to_thread(
            self._settings.update_enrichment_reasoning_effort,
            effort,
        )
        return self._enrichment_projection(row)

    async def test_connection(self) -> dict[str, Any]:
        """用当前保存的配置发起一次最小模型调用，验证连通性（真实请求一次）。

        走与富化/聊天一致的 get_chat_model 路径，HTTP 恒 200：
        status=success/failed 表达业务结果，失败只回显异常类型 + 分类排查
        文案，原始异常（可能含 Base URL、鉴权细节）只进服务端日志。
        """
        from backend.app.core.model_factory import get_chat_model

        projection = await self.get_config()
        base: dict[str, Any] = {
            "provider": projection.provider,
            "base_url": projection.base_url,
            "model_name": projection.model_name,
            "latency_ms": None,
        }
        if not projection.api_key_configured:
            return {
                **base,
                "status": "failed",
                "message": "未配置 API Key，请先保存模型服务配置。",
            }
        try:
            # 历史落库（本校验上线前写入）的 Base URL 同样不得触达内网
            validate_admin_base_url(projection.base_url)
        except InvalidProviderBaseUrl as exc:
            return {
                **base,
                "status": "failed",
                "message": str(exc),
            }
        started = time.monotonic()
        try:
            llm = get_chat_model(temperature=0)
            await asyncio.wait_for(
                asyncio.to_thread(llm.invoke, "ping，请只回复 pong"),
                timeout=_TEST_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            return {
                **base,
                "status": "failed",
                "message": f"连接测试超时（{_TEST_TIMEOUT_SECONDS:.0f}s 无响应），请检查 Base URL 与网络代理。",
            }
        except Exception as exc:  # noqa: BLE001 - 测试入口需按异常类型给管理员分类提示
            logger.warning("[Ops] 模型服务连接测试失败：%s", exc, exc_info=True)
            # 不回显异常类型名：SDK 异常类名可指纹化内部栈与代理结构（渗透审计 SSRF-2）
            return {
                **base,
                "status": "failed",
                "message": f"连接测试失败：{_classify_test_failure(exc)}。",
            }
        latency_ms = int((time.monotonic() - started) * 1000)
        return {
            **base,
            "status": "success",
            "message": f"连接正常：{projection.provider} / {projection.model_name} 响应耗时 {latency_ms}ms。",
            "latency_ms": latency_ms,
        }
