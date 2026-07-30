from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

from backend.app.services.ops_diagnostics import OpsDiagnosticsService


def test_diagnostics_delegates_readiness_shadow_and_finalization() -> None:
    readiness = MagicMock(return_value={"runtime_ready": True})
    snapshot = MagicMock(return_value={"epoch": "search-v2"})
    finalizer = MagicMock(return_value={"lifecycle": "finalized"})
    service = OpsDiagnosticsService(
        readiness=readiness,
        shadow_snapshot=snapshot,
        shadow_finalizer=finalizer,
        shadow_shutdown_timeout=4.5,
        website_taxonomy=[],
    )

    assert asyncio.run(service.project_catalog_readiness()) == {"runtime_ready": True}
    assert service.project_search_shadow_status() == {"epoch": "search-v2"}
    assert asyncio.run(service.finalize_project_shadow()) == {
        "search": {"lifecycle": "finalized"}
    }
    readiness.assert_called_once_with()
    snapshot.assert_called_once_with()
    finalizer.assert_called_once_with(4.5)


def test_project_taxonomy_returns_only_public_projection() -> None:
    service = OpsDiagnosticsService(
        readiness=MagicMock(),
        shadow_snapshot=MagicMock(),
        shadow_finalizer=MagicMock(),
        shadow_shutdown_timeout=1.0,
        website_taxonomy=[
            {
                "slug": "developer-tools",
                "name": "开发工具",
                "internal": "ignored",
                "children": [
                    {"slug": "code", "name": "代码", "internal": "ignored"}
                ],
            }
        ],
    )

    assert service.project_taxonomy() == [
        {
            "slug": "developer-tools",
            "name": "开发工具",
            "children": [{"slug": "code", "name": "代码"}],
        }
    ]
