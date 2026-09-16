from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from backend.app.repositories.postgres_attachment_meta_repository import (
    PostgresAttachmentMetaRepository,
)
from backend.app.services.chat import attachment_service
from backend.app.services.chat.attachment_policy import ValidatedImage
from backend.app.services.chat.attachment_service import _PostgresMetaStore
from backend.tests.postgres_test_safety import postgres_test_sandbox


@pytest.fixture
def database():
    with postgres_test_sandbox() as sandbox:
        with sandbox.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO users (email, hashed_password) VALUES
                    ('owner@example.com', 'hash'),
                    ('other@example.com', 'hash')
                """
            )
        yield sandbox.database


def test_attachment_meta_round_trip_owner_scope_and_order(database) -> None:
    repository = PostgresAttachmentMetaRepository(database)
    repository.upsert_attachment_meta(
        attachment_id="first",
        user_id=1,
        attachment_type="pdf",
        status="processing",
        file_name="a.pdf",
        mime_type="application/pdf",
        size_bytes=10,
        created_at=100.0,
        storage_path="/uploads/first.pdf",
    )
    repository.upsert_attachment_meta(
        attachment_id="second",
        user_id=1,
        attachment_type="image",
        status="ready",
        file_name="b.png",
        mime_type="image/png",
        size_bytes=5,
        created_at=200.0,
        expires_at=800.0,
    )
    repository.upsert_attachment_meta(
        attachment_id="foreign",
        user_id=2,
        attachment_type="image",
        status="ready",
        created_at=300.0,
    )

    row = repository.get_attachment_meta("first", user_id=1)
    assert row is not None
    assert row["attachment_type"] == "pdf"
    assert row["status"] == "processing"
    assert row["storage_path"] == "/uploads/first.pdf"
    assert repository.get_attachment_meta("first", user_id=2) is None
    assert repository.get_attachment_meta("missing", user_id=1) is None

    # 请求顺序与重复项保持，owner 过滤生效。
    rows = repository.list_attachment_meta(["second", "missing", "first", "second", "foreign"], user_id=1)
    assert [row["attachment_id"] for row in rows] == ["second", "first", "second"]
    assert repository.list_attachment_meta([], user_id=1) == []


def test_attachment_meta_upsert_updates_status_transition(database) -> None:
    repository = PostgresAttachmentMetaRepository(database)
    repository.upsert_attachment_meta(
        attachment_id="doc",
        user_id=1,
        attachment_type="pdf",
        status="processing",
        file_name="doc.pdf",
        mime_type="application/pdf",
        created_at=100.0,
    )
    repository.upsert_attachment_meta(
        attachment_id="doc",
        user_id=1,
        attachment_type="pdf",
        status="ready",
        file_name="doc.pdf",
        mime_type="application/pdf",
        page_count=3,
        text_preview="preview",
        created_at=100.0,
    )

    row = repository.get_attachment_meta("doc", user_id=1)
    assert row is not None
    assert row["status"] == "ready"
    assert row["page_count"] == 3
    assert row["text_preview"] == "preview"


def test_attachment_meta_existing_ids_and_expiry_purge(database) -> None:
    repository = PostgresAttachmentMetaRepository(database)
    for attachment_id, expires_at in (("kept", 0.0), ("stale", 700.0), ("fresh", 1700.0)):
        repository.upsert_attachment_meta(
            attachment_id=attachment_id,
            user_id=1,
            attachment_type="image" if expires_at else "pdf",
            status="ready",
            created_at=100.0,
            expires_at=expires_at,
        )

    assert repository.existing_attachment_ids(["kept", "stale", "unknown"]) == {
        "kept",
        "stale",
    }
    assert repository.delete_expired_attachment_meta(1000.0) == 1
    assert repository.existing_attachment_ids(["kept", "stale", "fresh"]) == {
        "kept",
        "fresh",
    }
    assert repository.delete_expired_attachment_meta(1000.0) == 0


def test_attachment_meta_enforces_user_foreign_key(database) -> None:
    repository = PostgresAttachmentMetaRepository(database)

    with pytest.raises(Exception) as user_error:
        repository.upsert_attachment_meta(
            attachment_id="no-user",
            user_id=999,
            attachment_type="image",
            status="ready",
            created_at=100.0,
        )
    assert getattr(user_error.value, "sqlstate", None) == "23503"


def test_image_service_full_chain_survives_restart_and_expires_metadata(database) -> None:
    """上传 → 元数据落库 → 新实例（重启模拟）→ owner 隔离 → 到期清理。"""
    repository = PostgresAttachmentMetaRepository(database)
    store = _PostgresMetaStore(repository)
    content = ValidatedImage(
        data=b"\xff\xd8\xfffixture",
        base64_data="/9j/Zml4dHVyZQ==",
        mime_type="image/jpeg",
        filename="photo.jpg",
    )

    with (
        patch.object(attachment_service.time, "time", return_value=1000.0),
        patch.object(attachment_service, "_meta_repository", repository),
        patch.object(attachment_service, "_meta_store", store),
    ):
        meta = asyncio.run(attachment_service.upload_image(content, user_id=1))
        assert meta.status == attachment_service.AttachmentStatus.READY

        # 重启模拟：同一数据库上的全新仓储与服务适配实例。
        restarted_repository = PostgresAttachmentMetaRepository(database)
        restarted_store = _PostgresMetaStore(restarted_repository)
        with (
            patch.object(attachment_service, "_meta_repository", restarted_repository),
            patch.object(attachment_service, "_meta_store", restarted_store),
        ):

            async def exercise() -> None:
                restored = await attachment_service.get_attachment(meta.id, 1)
                assert restored is not None
                assert restored.status == attachment_service.AttachmentStatus.READY
                assert restored.expires_at == 1600.0
                assert await attachment_service.get_attachment(meta.id, 2) is None
                assert await attachment_service.get_image_base64(meta.id, 1) == (
                    content.base64_data,
                    content.mime_type,
                )

            asyncio.run(exercise())

            result = attachment_service.reconcile_orphan_attachments(now=1600.001)
            assert result == {"orphan_files_removed": 0, "expired_rows_removed": 1}
            assert restarted_repository.get_attachment_meta(meta.id) is None
