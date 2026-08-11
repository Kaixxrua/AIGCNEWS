from __future__ import annotations

import asyncio
from datetime import date
from typing import Any

import pytest

from backend.app.services.ingestion import source_producthunt as ph


def test_legacy_policy_parser_and_transport_wrappers_forward_at_call_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    anchor = date(2026, 7, 27)
    sentinel_date = date(2026, 7, 26)
    sentinel_posts = [{"id": "forwarded"}]

    monkeypatch.setattr(ph.producthunt_policy, "resolve_anchor", lambda value: anchor)
    monkeypatch.setattr(
        ph.producthunt_policy, "parse_featured_at", lambda value: sentinel_date
    )
    monkeypatch.setattr(
        ph.producthunt_policy,
        "within_period",
        lambda featured, period, value: featured is sentinel_date and value is anchor,
    )
    monkeypatch.setattr(
        ph.producthunt_parser, "extract_posts_from_html", lambda html: sentinel_posts
    )

    async def curl(url: str) -> str:
        return f"curl:{url}"

    async def httpx(url: str) -> str:
        return f"httpx:{url}"

    async def html(url: str) -> str:
        return f"html:{url}"

    monkeypatch.setattr(ph.producthunt_transport, "fetch_html_curl_cffi", curl)
    monkeypatch.setattr(ph.producthunt_transport, "fetch_html_httpx", httpx)
    monkeypatch.setattr(ph.producthunt_transport, "fetch_html", html)

    assert ph._resolve_anchor("ignored") is anchor
    assert ph._parse_featured_at("ignored") is sentinel_date
    assert ph._within_period(sentinel_date, "daily", anchor) is True
    assert ph._extract_posts_from_html("ignored") is sentinel_posts
    assert asyncio.run(ph._fetch_html_curl_cffi("url")) == "curl:url"
    assert asyncio.run(ph._fetch_html_httpx("url")) == "httpx:url"
    assert asyncio.run(ph._fetch_html("url")) == "html:url"


def test_legacy_api_wrapper_forwards_transport_output_to_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    edges = [{"node": {"id": "101"}}]
    expected = [{"title": "forwarded"}]
    calls: list[tuple[Any, ...]] = []

    async def api_edges(limit: int, board_date: Any = None) -> list[dict[str, Any]]:
        assert limit == 3
        assert board_date == date(2026, 7, 27)
        return edges

    def project(*args: Any) -> list[dict[str, Any]]:
        calls.append(args)
        return expected

    monkeypatch.setattr(ph.producthunt_transport, "fetch_api_edges", api_edges)
    monkeypatch.setattr(ph.producthunt_projection, "project_api_items", project)

    result = asyncio.run(
        ph._fetch_via_api(
            3,
            "daily",
            date(2026, 7, 27),
            "producthunt_daily_html",
            "2026-07-27",
        )
    )

    assert result is expected
    assert calls == [
        (
            edges,
            "daily",
            date(2026, 7, 27),
            "producthunt_daily_html",
            "2026-07-27",
        )
    ]

    async def no_edges(_: int, __: Any = None) -> None:
        return None

    monkeypatch.setattr(ph.producthunt_transport, "fetch_api_edges", no_edges)
    calls.clear()
    assert (
        asyncio.run(
            ph._fetch_via_api(
                3,
                "daily",
                date(2026, 7, 27),
                "producthunt_daily_html",
                "2026-07-27",
            )
        )
        is None
    )
    assert calls == []


def test_public_async_entry_delegates_only_public_arguments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = [{"title": "from-coordinator"}]
    calls: list[dict[str, Any]] = []

    async def coordinated_fetch(**kwargs: Any) -> list[dict[str, Any]]:
        calls.append(kwargs)
        return expected

    monkeypatch.setattr(
        ph.producthunt_coordinator, "fetch_producthunt_products", coordinated_fetch
    )

    result = asyncio.run(
        ph.fetch_producthunt_products_async(3, " WEEKLY ", "2026-07-20")
    )

    assert result is expected
    assert calls == [
        {"limit": 3, "period": " WEEKLY ", "target_date": "2026-07-20"}
    ]


def test_sync_wrapper_works_without_and_inside_running_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_fetch(
        limit: int = 20, period: str = "daily", target_date: str | None = None
    ) -> list[dict[str, Any]]:
        return [{"limit": limit, "period": period, "target_date": target_date}]

    monkeypatch.setattr(ph, "fetch_producthunt_products_async", fake_fetch)
    expected = [{"limit": 3, "period": "weekly", "target_date": "2026-07-20"}]

    assert ph.fetch_producthunt_products(3, "weekly", "2026-07-20") == expected

    async def call_from_loop() -> list[dict[str, Any]]:
        return ph.fetch_producthunt_products(3, "weekly", "2026-07-20")

    assert asyncio.run(call_from_loop()) == expected
