from __future__ import annotations

import pytest

from backend.app.repositories.postgres_conversation_repository import (
    PostgresConversationRepository,
)
from backend.app.repositories.postgres_user_account_repository import (
    PostgresUserAccountRepository,
)
from backend.tests.postgres_test_safety import postgres_test_sandbox


@pytest.fixture
def database():
    with postgres_test_sandbox() as sandbox:
        yield sandbox.database


@pytest.fixture
def owners(database):
    accounts = PostgresUserAccountRepository(database)
    return (
        accounts.create_user_with_email("owner@example.com", "hash"),
        accounts.create_user_with_email("other@example.com", "hash"),
    )


def test_postgres_conversation_round_trip_owner_scope_order_and_json(database, owners) -> None:
    owner_id, other_id = owners
    repository = PostgresConversationRepository(database)

    first = repository.append_message_pair(
        user_id=owner_id,
        conversation_id=None,
        scope="global",
        scope_key=None,
        user_message="First question",
        assistant_content="First answer",
        assistant_thinking="private reasoning",
        sources=[{"id": "doc-1", "score": 0.9}],
        max_messages=10,
    )
    conversation_id = int(first["conversation"]["id"])
    second = repository.append_message_pair(
        user_id=owner_id,
        conversation_id=conversation_id,
        scope="global",
        scope_key=None,
        user_message="Second question",
        assistant_content="Second answer",
        parent_message_id=int(first["assistant_message"]["id"]),
        max_messages=10,
    )

    context = repository.get_owned_conversation_context(user_id=owner_id, conversation_id=conversation_id)
    assert context is not None
    assert [item["content"] for item in context["messages"]] == [
        "First question",
        "First answer",
        "Second question",
        "Second answer",
    ]
    assert context["messages"][1]["sources"] == [{"id": "doc-1", "score": 0.9}]
    assert context["messages"][1]["thinking_preview"] == "private reasoning"
    assert context["conversation"]["message_count"] == 4
    assert context["conversation"]["last_message_preview"] == "Second answer"
    assert repository.get_owned_conversation_context(user_id=other_id, conversation_id=conversation_id) is None
    assert not repository.delete_owned_conversation(user_id=other_id, conversation_id=conversation_id)
    assert repository.list_conversations(user_id=other_id)["total"] == 0
    assert second["assistant_message"]["parent_message_id"] == second["user_message"]["id"]


def test_postgres_branch_regeneration_and_retention_refresh_counts(database, owners) -> None:
    owner_id, _ = owners
    repository = PostgresConversationRepository(database)
    first = repository.append_message_pair(
        user_id=owner_id,
        conversation_id=None,
        scope="paper",
        scope_key="paper-1",
        user_message="Question one",
        assistant_content="Answer one",
        max_messages=10,
    )
    conversation_id = int(first["conversation"]["id"])
    second = repository.append_message_pair(
        user_id=owner_id,
        conversation_id=conversation_id,
        scope="paper",
        scope_key="paper-1",
        user_message="Question two",
        assistant_content="Answer two",
        max_messages=10,
    )

    regeneration = repository.prepare_owned_regeneration(user_id=owner_id, message_id=int(second["user_message"]["id"]))
    assert regeneration is not None
    assert regeneration["deleted_ids"] == [
        second["user_message"]["id"],
        second["assistant_message"]["id"],
    ]
    assert regeneration["target_message"]["content"] == "Question two"
    assert [item["content"] for item in regeneration["messages"]] == [
        "Question one",
        "Answer one",
    ]
    assert regeneration["conversation"]["message_count"] == 2
    assert regeneration["conversation"]["last_message_preview"] == "Answer one"

    retained = repository.append_message_pair(
        user_id=owner_id,
        conversation_id=conversation_id,
        scope="paper",
        scope_key="paper-1",
        user_message="Question three",
        assistant_content="Answer three",
        max_messages=2,
    )
    assert [item["content"] for item in retained["messages"]] == [
        "Question three",
        "Answer three",
    ]
    assert retained["conversation"]["message_count"] == 2
    assert repository.count_user_messages_today(owner_id) == 1


def test_postgres_append_rolls_back_pair_when_parent_is_foreign(database, owners) -> None:
    owner_id, other_id = owners
    repository = PostgresConversationRepository(database)
    owner = repository.create_conversation(user_id=owner_id)
    foreign = repository.append_message_pair(
        user_id=other_id,
        conversation_id=None,
        scope="global",
        scope_key=None,
        user_message="Foreign question",
        assistant_content="Foreign answer",
    )

    with pytest.raises(ValueError, match="message_not_found"):
        repository.append_message_pair(
            user_id=owner_id,
            conversation_id=int(owner["id"]),
            scope="global",
            scope_key=None,
            user_message="Must roll back",
            assistant_content="Must also roll back",
            parent_message_id=int(foreign["assistant_message"]["id"]),
        )

    context = repository.get_owned_conversation_context(user_id=owner_id, conversation_id=int(owner["id"]))
    assert context is not None
    assert context["messages"] == []
    assert context["conversation"]["message_count"] == 0


def test_postgres_scope_conversation_is_singleton_across_ensure_and_create(database, owners) -> None:
    owner_id, _ = owners
    repository = PostgresConversationRepository(database)

    first = repository.ensure_conversation(user_id=owner_id, scope="global", scope_key=None)
    again = repository.ensure_conversation(user_id=owner_id, scope="global", scope_key=None)
    assert int(again["id"]) == int(first["id"])

    # 「强制新建」与既有 scope 冲突时返回既有会话：uq_conv_user_scope_key
    # 唯一索引下不再产生 (user_id, scope, scope_key) 重复行
    created = repository.create_conversation(user_id=owner_id, scope="global", scope_key=None)
    assert int(created["id"]) == int(first["id"])

    paper = repository.ensure_conversation(user_id=owner_id, scope="paper", scope_key="paper-1")
    assert int(paper["id"]) != int(first["id"])
    assert int(repository.ensure_conversation(user_id=owner_id, scope="paper", scope_key="paper-1")["id"]) == int(
        paper["id"]
    )
    assert repository.list_conversations(user_id=owner_id)["total"] == 2
