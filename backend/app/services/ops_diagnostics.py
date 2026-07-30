from __future__ import annotations

"""Operational diagnostics and static project administration views."""

import asyncio
from typing import Any, Callable

Diagnostic = Callable[[], dict[str, Any]]
ShadowFinalizer = Callable[[float], dict[str, Any]]


class OpsDiagnosticsService:
    def __init__(
        self,
        *,
        readiness: Diagnostic,
        shadow_snapshot: Diagnostic,
        shadow_finalizer: ShadowFinalizer,
        shadow_shutdown_timeout: float,
        website_taxonomy: tuple[dict[str, Any], ...] | list[dict[str, Any]],
    ) -> None:
        self._readiness = readiness
        self._shadow_snapshot = shadow_snapshot
        self._shadow_finalizer = shadow_finalizer
        self._shadow_shutdown_timeout = shadow_shutdown_timeout
        self._website_taxonomy = website_taxonomy

    async def project_catalog_readiness(self) -> dict[str, Any]:
        return await asyncio.to_thread(self._readiness)

    def project_search_shadow_status(self) -> dict[str, Any]:
        return self._shadow_snapshot()

    async def finalize_project_shadow(self) -> dict[str, Any]:
        search = await asyncio.to_thread(
            self._shadow_finalizer,
            self._shadow_shutdown_timeout,
        )
        return {"search": search}

    def project_taxonomy(self) -> list[dict[str, Any]]:
        return [
            {
                "slug": category["slug"],
                "name": category["name"],
                "children": [
                    {"slug": child["slug"], "name": child["name"]}
                    for child in category.get("children", [])
                ],
            }
            for category in self._website_taxonomy
        ]
