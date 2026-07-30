from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from backend.app.services.project_search_runtime import (
    ApplicationProjectSearchRuntime,
)


def _config(**overrides):
    values = {
        "project_semantic_search_enabled": True,
        "project_search_shadow_workers": 1,
        "project_search_shadow_capacity": 1,
        "project_search_shadow_sample_rate": 0.0,
        "project_search_shadow_timeout_seconds": 1.0,
        "project_search_shadow_recent_case_limit": 2,
        "project_search_shadow_epoch": "test",
        "project_search_shadow_shutdown_timeout_seconds": 0.1,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_search_delegates_through_runtime_owned_factories() -> None:
    repository_factory = MagicMock()
    fallback_search = MagicMock()
    semantic = MagicMock()
    reranker = MagicMock()
    shadow = MagicMock()
    runtime = ApplicationProjectSearchRuntime(
        config=_config(),
        repository_factory=repository_factory,
        fallback_search=fallback_search,
        semantic_search_factory=MagicMock(return_value=semantic),
        reranker_factory=MagicMock(return_value=reranker),
        shadow_manager_factory=MagicMock(return_value=shadow),
    )
    result = {"items": [], "total": 0}

    with patch(
        "backend.app.services.project_search_runtime.search_projects",
        new=AsyncMock(return_value=result),
    ) as search:
        assert asyncio.run(runtime.search_projects(query="agents")) == result

    arguments = search.await_args.kwargs
    assert arguments["query"] == "agents"
    assert arguments["fallback_search"] is fallback_search
    assert arguments["repository_factory"] is repository_factory
    assert arguments["semantic_search_factory"]() is semantic
    assert arguments["semantic_search_factory"]() is semantic
    assert arguments["reranker_factory"]() is reranker
    assert arguments["reranker_factory"]() is reranker
    assert arguments["shadow_manager_factory"]() is shadow
    assert arguments["shadow_manager_factory"]() is shadow


def test_runtime_owned_options_cannot_be_overridden_by_callers() -> None:
    fallback_search = MagicMock(name="runtime_fallback")
    injected_fallback = MagicMock(name="caller_fallback")
    runtime = ApplicationProjectSearchRuntime(
        config=_config(),
        fallback_search=fallback_search,
    )

    with patch(
        "backend.app.services.project_search_runtime.search_projects",
        new=AsyncMock(return_value={}),
    ) as search:
        asyncio.run(
            runtime.search_projects(
                query="agents",
                fallback_search=injected_fallback,
            )
        )

    assert search.await_args.kwargs["fallback_search"] is fallback_search


def test_semantic_warmup_is_lazy_disabled_and_retryable() -> None:
    disabled_factory = MagicMock()
    disabled = ApplicationProjectSearchRuntime(
        config=_config(project_semantic_search_enabled=False),
        semantic_search_factory=disabled_factory,
    )
    assert disabled.warmup_semantic_search() == {"status": "disabled"}
    disabled_factory.assert_not_called()

    semantic = MagicMock()
    semantic.warmup.side_effect = [RuntimeError("temporary"), None]
    runtime = ApplicationProjectSearchRuntime(
        config=_config(),
        semantic_search_factory=MagicMock(return_value=semantic),
    )
    failed = runtime.warmup_semantic_search()
    succeeded = runtime.warmup_semantic_search()

    assert failed == {"status": "failed", "error": "temporary"}
    assert succeeded == {"status": "success"}


def test_semantic_warmup_reports_concurrent_attempt() -> None:
    runtime = ApplicationProjectSearchRuntime(config=_config())
    runtime._warmup_lock.acquire()
    try:
        assert runtime.warmup_semantic_search() == {"status": "already_running"}
    finally:
        runtime._warmup_lock.release()


def test_shadow_diagnostics_do_not_construct_manager_until_requested() -> None:
    shadow = MagicMock()
    shadow.snapshot.return_value = {"enabled": True, "epoch": "test"}
    shadow_factory = MagicMock(return_value=shadow)
    runtime = ApplicationProjectSearchRuntime(
        config=_config(),
        shadow_manager_factory=shadow_factory,
    )

    snapshot = runtime.project_search_shadow_snapshot()
    final = runtime.finalize_project_search_shadow()

    assert snapshot["enabled"] is False
    assert final["enabled"] is False
    shadow_factory.assert_not_called()

    manager = runtime._get_shadow_manager()
    assert manager is shadow
    assert runtime.project_search_shadow_snapshot() == {
        "enabled": True,
        "epoch": "test",
    }
    runtime.finalize_project_search_shadow(0.25)
    shadow.close.assert_called_once_with(0.25)


def test_close_is_idempotent_and_failure_isolated() -> None:
    semantic = MagicMock()
    semantic.close.side_effect = RuntimeError("semantic close")
    reranker = MagicMock()
    reranker.close = AsyncMock(side_effect=RuntimeError("reranker close"))
    shadow = MagicMock()
    shadow.close.side_effect = RuntimeError("shadow close")
    runtime = ApplicationProjectSearchRuntime(
        config=_config(project_search_shadow_shutdown_timeout_seconds=0.25),
        semantic_search_factory=MagicMock(return_value=semantic),
        reranker_factory=MagicMock(return_value=reranker),
        shadow_manager_factory=MagicMock(return_value=shadow),
    )
    runtime._get_semantic_search()
    runtime._get_reranker()
    runtime._get_shadow_manager()

    asyncio.run(runtime.close())
    asyncio.run(runtime.close())

    semantic.close.assert_called_once_with()
    reranker.close.assert_awaited_once_with()
    shadow.close.assert_called_once_with(0.25)
