"""采集管道可插拔源门控契约（3D）。

- composition：x_source_enabled 关闭时不注册 X 爬虫工厂，管道整体跳过该源
- XCrawler：缺省 transport 改经 source_plugins loader 解析实现类；
  开关关闭/插件缺失时构造即抛 XTransportUnavailable（fail closed）
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from backend.app.core.config import settings
from backend.app.services.ingestion import composition
from backend.app.services.ingestion.crawlers import x_crawler
from backend.app.services.source_plugins.x_source import XTransportUnavailable

EXPECTED_ALWAYS_ON_SOURCES = {
    "arxiv",
    "github",
    "news",
    "producthunt",
    "hackernews",
    "dailyhot",
}


def _source_names(factories) -> set[str]:
    return {factory().source_name for factory in factories}


def test_composition_omits_x_crawler_when_source_disabled(monkeypatch) -> None:
    monkeypatch.setattr(settings, "x_source_enabled", False)
    dependencies = composition.provide_ingestion_dependencies(
        repositories=MagicMock()
    )
    names = _source_names(dependencies.crawler_factories)
    assert "x" not in names
    assert names == EXPECTED_ALWAYS_ON_SOURCES


def test_composition_registers_x_crawler_when_source_enabled(monkeypatch) -> None:
    monkeypatch.setattr(settings, "x_source_enabled", True)
    dependencies = composition.provide_ingestion_dependencies(
        repositories=MagicMock()
    )
    names = _source_names(dependencies.crawler_factories)
    assert names == EXPECTED_ALWAYS_ON_SOURCES | {"x"}


def test_x_crawler_default_transport_fails_closed_when_plugin_unavailable(
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "x_source_enabled", False)
    with pytest.raises(XTransportUnavailable):
        x_crawler.XCrawler()


def test_x_crawler_default_transport_comes_from_loader(monkeypatch) -> None:
    constructed: list[dict] = []

    class _FakeTransport:
        def __init__(self, **kwargs) -> None:
            constructed.append(kwargs)

    monkeypatch.setattr(
        x_crawler, "load_x_transport_class", lambda: _FakeTransport
    )

    def _credential_provider() -> list:
        return []

    crawler = x_crawler.XCrawler(credential_provider=_credential_provider)
    assert isinstance(crawler._transport, _FakeTransport)
    assert len(constructed) == 1
    assert constructed[0]["credential_provider"] is _credential_provider
    assert constructed[0]["inter_account_delay"] > 0
