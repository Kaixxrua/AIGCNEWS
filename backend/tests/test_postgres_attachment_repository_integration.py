from __future__ import annotations

import pytest

from backend.app.repositories.attachment_repository import AttachmentRepository
from backend.app.repositories.postgres_attachment_repository import (
    PostgresAttachmentRepository,
)
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
            connection.execute("INSERT INTO conversations (user_id, title) VALUES (1, 'test')")
        yield sandbox.database


def test_attachment_repository_round_trip_and_owner_scope(database) -> None:
    repository: AttachmentRepository = PostgresAttachmentRepository(database)

    row = repository.create_chat_attachment(
        user_id=1,
        conversation_id=1,
        file_name="paper.pdf",
        mime_type="application/pdf",
        modality="pdf",
        storage_path="papers/one.pdf",
        file_size=123,
        page_count=2,
        parse_status="ready",
        extract_text="content",
        meta={"source": "upload"},
    )

    assert row["id"] == 1
    assert row["meta"] == {"source": "upload"}
    assert repository.get_chat_attachment(1, user_id=1)["file_name"] == "paper.pdf"
    assert repository.get_chat_attachment(1, user_id=2) is None
    assert [item["id"] for item in repository.list_chat_attachments(user_id=1)] == [1]
    assert [item["id"] for item in repository.list_chat_attachments(user_id=1, conversation_id=1)] == [1]


def test_attachment_repository_enforces_owner_and_conversation_foreign_keys(database) -> None:
    repository = PostgresAttachmentRepository(database)

    with pytest.raises(Exception) as user_error:
        repository.create_chat_attachment(
            user_id=999,
            conversation_id=None,
            file_name="image.png",
            mime_type="image/png",
            modality="image",
        )
    assert getattr(user_error.value, "sqlstate", None) == "23503"

    with pytest.raises(Exception) as conversation_error:
        repository.create_chat_attachment(
            user_id=1,
            conversation_id=999,
            file_name="image.png",
            mime_type="image/png",
            modality="image",
        )
    assert getattr(conversation_error.value, "sqlstate", None) == "23503"
