from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import MagicMock

from backend.app.repositories.postgres_site_contact_page_repository import (
    PostgresSiteContactPageRepository,
)
from backend.app.repositories.site_contact_page_repository import (
    SiteContactEntry,
    SiteContactPage,
    SiteContactPageRepository,
    SiteContactServiceCard,
)


class FakeDatabase:
    def __init__(self, cursor: MagicMock) -> None:
        self.cursor = cursor
        self.connection = MagicMock()
        cursor_context = MagicMock()
        cursor_context.__enter__.return_value = cursor
        self.connection.cursor.return_value = cursor_context
        self.transaction_count = 0

    @contextmanager
    def transaction(self):
        self.transaction_count += 1
        yield self.connection


def _make_repository(cursor: MagicMock | None = None):
    cursor = cursor or MagicMock()
    database = FakeDatabase(cursor)
    return PostgresSiteContactPageRepository(database), database, cursor


def _page_row(**overrides):
    row = {
        "enabled": True,
        "nav_label": "合作",
        "title": "联系合作",
        "subtitle": "外包 · 商务合作",
        # 本仓 psycopg 行返回 jsonb 为原始字符串，读取侧必须 json.loads
        "service_cards": json.dumps(
            [{"title": "外包开发", "description": "AI 应用定制", "icon": "code"}],
            ensure_ascii=False,
        ),
        "contact_entries": json.dumps(
            [{"label": "QQ 群", "value": "123456", "href": "", "qr_image_url": "/qr.png"}],
            ensure_ascii=False,
        ),
        "body_markdown": "# 欢迎",
        "updated_at": datetime(2026, 8, 13, 10, 0, tzinfo=timezone.utc),
    }
    row.update(overrides)
    return row


def test_adapter_exposes_site_contact_page_repository_contract() -> None:
    repository, _, _ = _make_repository()
    contract: SiteContactPageRepository = repository

    assert callable(contract.get_site_contact_page)
    assert callable(contract.upsert_site_contact_page)


def test_get_returns_none_when_singleton_row_missing() -> None:
    repository, _, cursor = _make_repository()
    cursor.fetchone.return_value = None

    assert repository.get_site_contact_page() is None
    query = cursor.execute.call_args.args[0]
    assert "FROM site_contact_page" in query
    assert "WHERE id = 1" in query


def test_get_maps_row_with_jsonb_strings_to_page() -> None:
    repository, _, cursor = _make_repository()
    cursor.fetchone.return_value = _page_row()

    result = repository.get_site_contact_page()

    assert result == SiteContactPage(
        enabled=True,
        nav_label="合作",
        title="联系合作",
        subtitle="外包 · 商务合作",
        service_cards=(
            SiteContactServiceCard(title="外包开发", description="AI 应用定制", icon="code"),
        ),
        contact_entries=(
            SiteContactEntry(label="QQ 群", value="123456", href="", qr_image_url="/qr.png"),
        ),
        body_markdown="# 欢迎",
        updated_at=datetime(2026, 8, 13, 10, 0, tzinfo=timezone.utc),
    )


def test_get_tolerates_pre_parsed_jsonb_lists() -> None:
    repository, _, cursor = _make_repository()
    cursor.fetchone.return_value = _page_row(
        service_cards=[{"title": "咨询", "description": "", "icon": ""}],
        contact_entries=[],
    )

    result = repository.get_site_contact_page()

    assert result is not None
    assert result.service_cards == (SiteContactServiceCard(title="咨询"),)
    assert result.contact_entries == ()


def test_upsert_serializes_cards_and_entries_as_jsonb() -> None:
    repository, database, cursor = _make_repository()
    cursor.fetchone.return_value = _page_row()

    result = repository.upsert_site_contact_page(
        enabled=True,
        nav_label="  合作  ",
        title="联系合作",
        subtitle="外包 · 商务合作",
        service_cards=(
            SiteContactServiceCard(title="外包开发", description="AI 应用定制", icon="code"),
        ),
        contact_entries=(
            SiteContactEntry(label="QQ 群", value="123456", href="", qr_image_url="/qr.png"),
        ),
        body_markdown="# 欢迎",
    )

    assert result.title == "联系合作"
    query, params = cursor.execute.call_args.args
    assert "INSERT INTO site_contact_page" in query
    assert "%s::jsonb" in query
    assert "ON CONFLICT (id) DO UPDATE" in query
    assert "RETURNING" in query
    # nav_label/title/subtitle 入参经 strip；jsonb 字段为 ensure_ascii=False 的 JSON 字符串
    assert params == (
        True,
        "合作",
        "联系合作",
        "外包 · 商务合作",
        json.dumps(
            [{"title": "外包开发", "description": "AI 应用定制", "icon": "code"}],
            ensure_ascii=False,
        ),
        json.dumps(
            [{"label": "QQ 群", "value": "123456", "href": "", "qr_image_url": "/qr.png"}],
            ensure_ascii=False,
        ),
        "# 欢迎",
    )
    assert database.transaction_count == 1
