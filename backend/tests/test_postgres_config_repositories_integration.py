from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any, Iterator

import pytest

from backend.tests.postgres_test_safety import postgres_test_sandbox

_TESTS_DIR = Path(__file__).resolve().parent
_IMPORT_CWD = Path.cwd()
os.chdir(_TESTS_DIR)
try:
    psycopg = pytest.importorskip("psycopg")
    pytest.importorskip("psycopg_pool")

    from backend.app.repositories.postgres_briefing_repository import (
        PostgresBriefingRepository,
    )
    from backend.app.repositories.postgres_briefing_subscription_repository import (
        PostgresBriefingSubscriptionRepository,
    )
    from backend.app.repositories.postgres_evaluation_repository import (
        PostgresEvaluationRepository,
    )
    from backend.app.repositories.postgres_runtime_provider_repository import (
        PostgresRuntimeProviderSettingRepository,
    )
finally:
    os.chdir(_IMPORT_CWD)


@pytest.fixture(scope="module")
def database() -> Iterator[Any]:
    with postgres_test_sandbox() as sandbox:
        database = sandbox.database
        yield database


def _create_user(database: Any) -> int:
    with database.transaction() as connection:
        row = connection.execute(
            "INSERT INTO users (email, hashed_password) VALUES (%s, %s) RETURNING id",
            (f"runtime-{uuid.uuid4().hex}@example.com", "hash"),
        ).fetchone()
        return int(row["id"])


def test_real_runtime_provider_round_trip_preserves_secret_and_singleton(database) -> None:
    repository = PostgresRuntimeProviderSettingRepository(database)

    first = repository.upsert_runtime_provider_setting(
        " OpenAI ", " https://one.test ", " secret ", model_name=" model-one "
    )
    second = repository.upsert_runtime_provider_setting("Anthropic", "https://two.test", model_name="model-two")

    assert first["provider"] == "openai"
    assert second["provider"] == "anthropic"
    assert second["api_key"] == "secret"
    assert second["updated_at"] is not None
    assert repository.get_runtime_provider_setting("openai") is None
    assert repository.get_runtime_provider_setting()["provider"] == "anthropic"


def test_real_briefing_round_trip_preserves_text_time_and_preview(database) -> None:
    repository = PostgresBriefingRepository(database)
    content = "简报" * 60

    briefing_id = repository.save_briefing("2026-07-28", content)
    row = repository.get_briefing_by_date("2026-07-28")
    listed = repository.list_briefings(limit=1)

    assert row is not None
    assert row["id"] == briefing_id
    assert row["content"] == content
    assert isinstance(row["created_at"], str) and "+00:00" in row["created_at"]
    assert listed == [
        {
            "id": briefing_id,
            "date": "2026-07-28",
            "created_at": row["created_at"],
            "content_preview": content[:100],
        }
    ]


def test_real_subscription_reactivation_updates_explicit_timestamp(database) -> None:
    repository = PostgresBriefingSubscriptionRepository(database)
    user_id = _create_user(database)

    first = repository.upsert_briefing_subscription(user_id, "old@example.com")
    assert repository.cancel_briefing_subscription(user_id) is True
    second = repository.upsert_briefing_subscription(user_id, "new@example.com")

    assert second["id"] == first["id"]
    assert second["email"] == "new@example.com"
    assert second["is_active"] is True
    assert second["updated_at"] >= first["updated_at"]
    assert repository.get_user_briefing_subscriptions(user_id)[0]["id"] == first["id"]
    assert repository.get_active_subscribers()[0]["email"] == "new@example.com"


def test_real_evaluation_round_trip_preserves_json_text_and_aggregates(database) -> None:
    repository = PostgresEvaluationRepository(database)
    sources = [{"title": "中文资料", "rank": 1}]

    evaluation_id = repository.save_evaluation(
        query="query",
        answer="answer",
        sources=sources,
        recall_score=0.5,
        citation_score=0.75,
        subjective_score=1.0,
    )

    listed = repository.list_evaluations(limit=1)
    summary = repository.get_eval_summary()
    with database.transaction() as connection:
        stored = connection.execute(
            "SELECT sources_json, evaluated_at FROM rag_evaluations WHERE id = %s",
            (evaluation_id,),
        ).fetchone()

    assert listed[0]["id"] == evaluation_id
    assert isinstance(stored["sources_json"], str)
    assert json.loads(stored["sources_json"]) == sources
    assert isinstance(stored["evaluated_at"], str) and "+00:00" in stored["evaluated_at"]
    assert summary == {
        "total": 1,
        "avg_recall": 0.5,
        "avg_citation": 0.75,
        "avg_subjective": 1.0,
    }
