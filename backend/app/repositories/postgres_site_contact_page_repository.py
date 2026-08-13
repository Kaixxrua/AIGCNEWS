from __future__ import annotations

import json
from typing import Any

from backend.app.core.postgres_database import PostgresDatabaseLifecycle
from backend.app.repositories.site_contact_page_repository import (
    SiteContactEntry,
    SiteContactPage,
    SiteContactServiceCard,
)

_COLUMNS = (
    "enabled, nav_label, title, subtitle, service_cards, contact_entries, "
    "body_markdown, updated_at"
)


class PostgresSiteContactPageRepository:
    """PostgreSQL persistence for the singleton site contact page row (id = 1)."""

    def __init__(self, database: PostgresDatabaseLifecycle) -> None:
        self._database = database

    def get_site_contact_page(self) -> SiteContactPage | None:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT {_COLUMNS}
                    FROM site_contact_page
                    WHERE id = 1
                    """
                )
                row = cursor.fetchone()
                return self._row_to_page(row) if row else None

    def upsert_site_contact_page(
        self,
        *,
        enabled: bool,
        nav_label: str,
        title: str,
        subtitle: str,
        service_cards: tuple[SiteContactServiceCard, ...],
        contact_entries: tuple[SiteContactEntry, ...],
        body_markdown: str,
    ) -> SiteContactPage:
        cards_payload = json.dumps(
            [
                {"title": card.title, "description": card.description, "icon": card.icon}
                for card in service_cards
            ],
            ensure_ascii=False,
        )
        entries_payload = json.dumps(
            [
                {
                    "label": entry.label,
                    "value": entry.value,
                    "href": entry.href,
                    "qr_image_url": entry.qr_image_url,
                }
                for entry in contact_entries
            ],
            ensure_ascii=False,
        )

        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    INSERT INTO site_contact_page
                        (id, enabled, nav_label, title, subtitle, service_cards,
                         contact_entries, body_markdown, updated_at)
                    VALUES (1, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, CURRENT_TIMESTAMP)
                    ON CONFLICT (id) DO UPDATE SET
                        enabled = EXCLUDED.enabled,
                        nav_label = EXCLUDED.nav_label,
                        title = EXCLUDED.title,
                        subtitle = EXCLUDED.subtitle,
                        service_cards = EXCLUDED.service_cards,
                        contact_entries = EXCLUDED.contact_entries,
                        body_markdown = EXCLUDED.body_markdown,
                        updated_at = CURRENT_TIMESTAMP
                    RETURNING {_COLUMNS}
                    """,
                    (
                        bool(enabled),
                        (nav_label or "").strip(),
                        (title or "").strip(),
                        (subtitle or "").strip(),
                        cards_payload,
                        entries_payload,
                        body_markdown or "",
                    ),
                )
                row = cursor.fetchone()

        return self._row_to_page(row)

    def _row_to_page(self, row: dict[str, Any]) -> SiteContactPage:
        raw_cards = row["service_cards"]
        cards = json.loads(raw_cards) if isinstance(raw_cards, str) else (raw_cards or [])
        raw_entries = row["contact_entries"]
        entries = (
            json.loads(raw_entries) if isinstance(raw_entries, str) else (raw_entries or [])
        )
        return SiteContactPage(
            enabled=bool(row["enabled"]),
            nav_label=str(row["nav_label"]),
            title=str(row["title"]),
            subtitle=str(row["subtitle"]),
            service_cards=tuple(
                SiteContactServiceCard(
                    title=str(card.get("title", "")),
                    description=str(card.get("description", "")),
                    icon=str(card.get("icon", "")),
                )
                for card in cards
                if isinstance(card, dict)
            ),
            contact_entries=tuple(
                SiteContactEntry(
                    label=str(entry.get("label", "")),
                    value=str(entry.get("value", "")),
                    href=str(entry.get("href", "")),
                    qr_image_url=str(entry.get("qr_image_url", "")),
                )
                for entry in entries
                if isinstance(entry, dict)
            ),
            body_markdown=str(row["body_markdown"]),
            updated_at=row["updated_at"],
        )
