"""源装配加载器：特性开关门控 + 可选模块解析。

X transport 随公共仓发布。开关关闭返回 None；开关打开但候选不可导入时记
warning 并返回 None——fail closed，公共代码据此优雅降级。导入结果进程内缓存，测试经
``_reset_plugin_cache`` 重置。
"""

from __future__ import annotations

import importlib
import logging
from types import ModuleType
from typing import Any

logger = logging.getLogger(__name__)

# X 使用仓库内唯一 canonical transport。
_X_TRANSPORT_MODULES = (
    "backend.app.services.ingestion.sources.x_transport",
)

_module_cache: dict[str, ModuleType | None] = {}


def _reset_plugin_cache() -> None:
    """清空插件模块缓存（测试缝）。"""
    _module_cache.clear()


def _import_first(candidates: tuple[str, ...]) -> ModuleType | None:
    """按优先级导入首个可用候选；全部失败记 warning 返回 None。"""
    for name in candidates:
        if name not in _module_cache:
            try:
                _module_cache[name] = importlib.import_module(name)
            except ImportError:
                logger.debug("[source_plugins] 候选插件模块 %s 不可导入", name, exc_info=True)
                _module_cache[name] = None
        module = _module_cache[name]
        if module is not None:
            return module
    logger.warning(
        "[source_plugins] 源插件候选模块均不可导入：%s",
        ", ".join(candidates),
    )
    return None


def load_x_transport_class() -> type[Any] | None:
    """返回公共 XTransport 类；开关关闭或实现缺失/形状不符时返回 None。"""
    from backend.app.core.config import settings

    if not settings.x_source_enabled:
        return None
    module = _import_first(_X_TRANSPORT_MODULES)
    if module is None:
        return None
    transport_class = getattr(module, "XTransport", None)
    if transport_class is None:
        logger.warning("[source_plugins] 模块 %s 缺少 XTransport", module.__name__)
    return transport_class

