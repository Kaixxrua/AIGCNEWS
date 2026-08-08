from __future__ import annotations

import json
from contextlib import contextmanager
from unittest.mock import MagicMock

from backend.app.repositories.briefing_repository import (
    ActiveBriefingSubscriberReader,
    BriefingContentRepository,
    BriefingSubscriptionRepository,
)
from backend.app.repositories.evaluation_repository import EvaluationRepository
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
from backend.app.repositories.runtime_provider_repository import (
    RuntimeProviderSettingRepository,
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


def _cursor_database() -> tuple[FakeDatabase, MagicMock]:
    cursor = MagicMock()
    return FakeDatabase(cursor), cursor


def test_postgres_adapters_expose_existing_protocols() -> None:
    database, _ = _cursor_database()

    provider: RuntimeProviderSettingRepository = (
        PostgresRuntimeProviderSettingRepository(database)
    )
    briefings: BriefingContentRepository = PostgresBriefingRepository(database)
    subscriptions: BriefingSubscriptionRepository = (
        PostgresBriefingSubscriptionRepository(database)
    )
    subscribers: ActiveBriefingSubscriberReader = subscriptions
    evaluations: EvaluationRepository = PostgresEvaluationRepository(database)

    assert callable(provider.upsert_runtime_provider_setting)
    assert callable(briefings.list_briefings)
    assert callable(subscriptions.cancel_briefing_subscription)
    assert callable(subscribers.get_active_subscribers)
    assert callable(evaluations.get_eval_summary)


def test_provider_upsert_normalizes_values_preserves_secret_and_returns_row() -> None:
    database, cursor = _cursor_database()
    cursor.fetchone.side_effect = [
        {"api_key": "existing-secret", "enrichment_reasoning_effort": "low"},
        {
            "provider": "openai",
            "base_url": "https://example.test",
            "api_key": "existing-secret",
            "model_name": "gpt-test",
            "enrichment_reasoning_effort": "low",
            "updated_at": "database-time",
        },
    ]
    repository = PostgresRuntimeProviderSettingRepository(database)

    result = repository.upsert_runtime_provider_setting(
        " OpenAI ", " https://example.test ", model_name=" gpt-test "
    )

    assert result["api_key"] == "existing-secret"
    assert result["updated_at"] == "database-time"
    insert_call = cursor.execute.call_args_list[2]
    assert "RETURNING provider" in insert_call.args[0]
    assert "updated_at" in insert_call.args[0]
    # 富化专用推理强度不在表单内，单行重建时沿用旧值
    assert insert_call.args[1] == (
        "openai",
        "https://example.test",
        "existing-secret",
        "gpt-test",
        "",
        "low",
    )
    assert database.transaction_count == 1


def test_enrichment_reasoning_effort_update_rewrites_singleton_row() -> None:
    database, cursor = _cursor_database()
    cursor.rowcount = 1
    cursor.fetchone.return_value = {
        "provider": "openai",
        "enrichment_reasoning_effort": "high",
        "updated_at": "database-time",
    }
    repository = PostgresRuntimeProviderSettingRepository(database)

    result = repository.update_enrichment_reasoning_effort(" High ")

    update_call = cursor.execute.call_args_list[0]
    assert "UPDATE runtime_provider_settings" in update_call.args[0]
    assert "enrichment_reasoning_effort" in update_call.args[0]
    assert update_call.args[1] == ("high",)
    assert result["enrichment_reasoning_effort"] == "high"
    assert database.transaction_count == 1


def test_enrichment_reasoning_effort_update_inserts_row_when_table_empty() -> None:
    database, cursor = _cursor_database()
    cursor.rowcount = 0
    cursor.fetchone.return_value = {
        "provider": "",
        "enrichment_reasoning_effort": "low",
        "updated_at": "database-time",
    }
    repository = PostgresRuntimeProviderSettingRepository(database)

    result = repository.update_enrichment_reasoning_effort("low")

    insert_call = cursor.execute.call_args_list[1]
    assert "INSERT INTO runtime_provider_settings" in insert_call.args[0]
    assert insert_call.args[1] == ("low",)
    assert result["enrichment_reasoning_effort"] == "low"


def test_briefing_insert_uses_explicit_iso_text_time_and_returning_id() -> None:
    database, cursor = _cursor_database()
    cursor.fetchone.return_value = {"id": 7}

    result = PostgresBriefingRepository(database).save_briefing(
        "2026-07-28", "briefing"
    )

    assert result == 7
    sql, params = cursor.execute.call_args.args
    assert "RETURNING id" in sql
    assert params[:2] == ("2026-07-28", "briefing")
    assert isinstance(params[2], str) and "+00:00" in params[2]


def test_subscription_upsert_uses_conflict_transaction_and_boolean_shape() -> None:
    database, cursor = _cursor_database()
    row = {"id": 3, "is_active": True, "updated_at": "database-time"}
    cursor.fetchone.return_value = row
    repository = PostgresBriefingSubscriptionRepository(database)

    assert repository.upsert_briefing_subscription(4, "a@example.com") == row
    sql = cursor.execute.call_args.args[0]
    assert "ON CONFLICT (user_id, source, period)" in sql
    assert "updated_at = CURRENT_TIMESTAMP" in sql
    assert "RETURNING *" in sql

    cursor.rowcount = 1
    assert repository.cancel_briefing_subscription(4) is True
    assert "is_active = FALSE" in cursor.execute.call_args.args[0]
    assert database.transaction_count == 2


def test_evaluation_serializes_unicode_json_and_explicit_iso_text_time() -> None:
    database, cursor = _cursor_database()
    cursor.fetchone.return_value = {"id": 9}
    repository = PostgresEvaluationRepository(database)

    result = repository.save_evaluation(
        query="问题",
        answer="答案",
        sources=[{"title": "资料"}],
        recall_score=0.5,
        citation_score=0.75,
        subjective_score=1.0,
    )

    assert result == 9
    sql, params = cursor.execute.call_args.args
    assert "RETURNING id" in sql
    assert json.loads(params[2]) == [{"title": "资料"}]
    assert "资料" in params[2]
    assert isinstance(params[6], str) and "+00:00" in params[6]
