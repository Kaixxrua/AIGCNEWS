from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from backend.app.core.database import DatabaseLifecycle, mysql_database
from backend.app.repositories.mysql_repo import MySQLRepository


class MySQLRepositoryLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_schema_initialized = MySQLRepository._schema_initialized
        MySQLRepository._schema_initialized = True

    def tearDown(self) -> None:
        MySQLRepository._schema_initialized = self.original_schema_initialized

    def test_connect_delegates_to_injected_database(self) -> None:
        connection = MagicMock()
        database = MagicMock(spec=DatabaseLifecycle)
        database.connect.return_value = connection
        repository = MySQLRepository(database=database)

        self.assertIs(repository._connect(), connection)

        database.connect.assert_called_once_with()

    def test_defaults_to_shared_database_lifecycle(self) -> None:
        first_repository = MySQLRepository()
        second_repository = MySQLRepository()

        self.assertIs(first_repository._database, mysql_database)
        self.assertIs(second_repository._database, mysql_database)

    def test_ingestion_task_component_reuses_database_lifecycle(self) -> None:
        database = MagicMock(spec=DatabaseLifecycle)
        repository = MySQLRepository(database=database)

        first = repository.ingestion_tasks
        second = repository.ingestion_tasks

        self.assertIs(first, second)
        self.assertIs(first._database, database)

    def test_ingestion_task_component_does_not_create_pool(self) -> None:
        database = MagicMock(spec=DatabaseLifecycle)
        repository = MySQLRepository(database=database)

        _ = repository.ingestion_tasks

        database.connect.assert_not_called()

    def test_briefing_component_reuses_database_lifecycle(self) -> None:
        database = MagicMock(spec=DatabaseLifecycle)
        repository = MySQLRepository(database=database)

        first = repository.briefings
        second = repository.briefings

        self.assertIs(first, second)
        self.assertIs(first._database, database)
        self.assertIsNot(first, repository.ingestion_tasks)
        database.connect.assert_not_called()

    def test_subscription_component_reuses_database_lifecycle(self) -> None:
        database = MagicMock(spec=DatabaseLifecycle)
        repository = MySQLRepository(database=database)

        first = repository.briefing_subscriptions
        second = repository.briefing_subscriptions

        self.assertIs(first, second)
        self.assertIs(first._database, database)
        self.assertIsNot(first, repository.briefings)
        self.assertIsNot(first, repository.ingestion_tasks)
        database.connect.assert_not_called()

    def test_evaluation_component_reuses_database_lifecycle(self) -> None:
        database = MagicMock(spec=DatabaseLifecycle)
        repository = MySQLRepository(database=database)

        first = repository.evaluations
        second = repository.evaluations

        self.assertIs(first, second)
        self.assertIs(first._database, database)
        self.assertIsNot(first, repository.briefings)
        self.assertIsNot(first, repository.briefing_subscriptions)
        database.connect.assert_not_called()

    def test_mcp_server_config_component_reuses_database_lifecycle(self) -> None:
        database = MagicMock(spec=DatabaseLifecycle)
        repository = MySQLRepository(database=database)

        first = repository.mcp_server_configs
        second = repository.mcp_server_configs

        self.assertIs(first, second)
        self.assertIs(first._database, database)
        self.assertEqual(
            first._defaults,
            (
                ("arxiv", "Arxiv MCP", ""),
                ("github", "GitHub MCP", ""),
            ),
        )
        self.assertIsNot(first, repository.evaluations)
        database.connect.assert_not_called()

    def test_mcp_access_token_component_reuses_database_lifecycle(self) -> None:
        database = MagicMock(spec=DatabaseLifecycle)
        repository = MySQLRepository(database=database)

        first = repository.mcp_access_tokens
        second = repository.mcp_access_tokens

        self.assertIs(first, second)
        self.assertIs(first._database, database)
        self.assertIsNot(first, repository.mcp_server_configs)
        database.connect.assert_not_called()

    def test_user_account_component_reuses_database_lifecycle(self) -> None:
        database = MagicMock(spec=DatabaseLifecycle)
        repository = MySQLRepository(database=database)

        first = repository.user_accounts
        second = repository.user_accounts

        self.assertIs(first, second)
        self.assertIs(first._database, database)
        self.assertIsNot(first, repository.mcp_server_configs)
        database.connect.assert_not_called()

    def test_preserves_single_schema_initialization(self) -> None:
        MySQLRepository._schema_initialized = False
        database = MagicMock(spec=DatabaseLifecycle)

        with patch.object(MySQLRepository, "_init_schema") as initialize_schema:
            MySQLRepository(database=database)
            MySQLRepository(database=database)

        initialize_schema.assert_called_once_with()
        self.assertTrue(MySQLRepository._schema_initialized)

    def test_repository_connection_close_returns_through_shared_pool(self) -> None:
        connection = MagicMock()
        pool = MagicMock()
        pool.connection.return_value = connection
        database = DatabaseLifecycle(MagicMock(return_value=pool))
        repository = MySQLRepository(database=database)

        acquired = repository._connect()
        acquired.close()

        self.assertIs(acquired, connection)
        pool.connection.assert_called_once_with()
        connection.close.assert_called_once_with()
        pool.close.assert_not_called()

    def test_task_compatibility_methods_delegate_to_component(self) -> None:
        repository = MySQLRepository(database=MagicMock(spec=DatabaseLifecycle))
        task_repository = MagicMock()
        task_repository.create_task.return_value = 42
        task_repository.get_latest_task.return_value = {"id": 42}
        task_repository.get_recent_tasks.return_value = [{"id": 42}]
        task_repository.list_tasks.return_value = {"items": [{"id": 42}]}
        task_repository.clear_all_tasks.return_value = 1
        repository._ingestion_tasks = task_repository

        self.assertEqual(repository.create_task("multi_source_ingest"), 42)
        repository.finish_task(
            42,
            status="failed",
            error_msg="sentinel",
            item_count=3,
        )
        self.assertEqual(repository.get_latest_task(), {"id": 42})
        self.assertEqual(repository.get_recent_tasks(limit=7), [{"id": 42}])
        self.assertEqual(repository.list_tasks(page=2, page_size=3), {"items": [{"id": 42}]})
        self.assertEqual(repository.clear_all_tasks(), 1)

        task_repository.create_task.assert_called_once_with("multi_source_ingest")
        task_repository.finish_task.assert_called_once_with(
            42,
            status="failed",
            error_msg="sentinel",
            item_count=3,
        )
        task_repository.get_latest_task.assert_called_once_with()
        task_repository.get_recent_tasks.assert_called_once_with(7)
        task_repository.list_tasks.assert_called_once_with(2, 3)
        task_repository.clear_all_tasks.assert_called_once_with()

    def test_briefing_compatibility_methods_delegate_to_component(self) -> None:
        repository = MySQLRepository(database=MagicMock(spec=DatabaseLifecycle))
        briefing_repository = MagicMock()
        briefing_repository.save_briefing.return_value = 42
        briefing_repository.get_latest_briefing.return_value = {"id": 42}
        briefing_repository.get_briefing_by_date.return_value = {"id": 43}
        briefing_repository.list_briefings.return_value = [{"id": 42}]
        repository._briefings = briefing_repository

        self.assertEqual(repository.save_briefing("2026-07-22", "content"), 42)
        self.assertEqual(repository.get_latest_briefing(), {"id": 42})
        self.assertEqual(repository.get_briefing_by_date("2026-07-22"), {"id": 43})
        self.assertEqual(repository.list_briefings(limit=7), [{"id": 42}])

        briefing_repository.save_briefing.assert_called_once_with(
            "2026-07-22",
            "content",
        )
        briefing_repository.get_latest_briefing.assert_called_once_with()
        briefing_repository.get_briefing_by_date.assert_called_once_with("2026-07-22")
        briefing_repository.list_briefings.assert_called_once_with(7)

    def test_evaluation_compatibility_methods_delegate_to_component(self) -> None:
        repository = MySQLRepository(database=MagicMock(spec=DatabaseLifecycle))
        evaluation_repository = MagicMock()
        evaluation_repository.save_evaluation.return_value = 42
        evaluation_repository.get_eval_summary.return_value = {"total": 1}
        evaluation_repository.list_evaluations.return_value = [{"id": 42}]
        repository._evaluations = evaluation_repository
        sources = [{"title": "source"}]

        self.assertEqual(
            repository.save_evaluation(
                query="query",
                answer="answer",
                sources=sources,
                recall_score=0.5,
                citation_score=0.25,
                subjective_score=0.0,
            ),
            42,
        )
        self.assertEqual(repository.get_eval_summary(), {"total": 1})
        self.assertEqual(repository.list_evaluations(limit=7), [{"id": 42}])

        evaluation_repository.save_evaluation.assert_called_once_with(
            query="query",
            answer="answer",
            sources=sources,
            recall_score=0.5,
            citation_score=0.25,
            subjective_score=0.0,
        )
        evaluation_repository.get_eval_summary.assert_called_once_with()
        evaluation_repository.list_evaluations.assert_called_once_with(7)

    def test_mcp_server_compatibility_methods_delegate_to_component(self) -> None:
        repository = MySQLRepository(database=MagicMock(spec=DatabaseLifecycle))
        mcp_repository = MagicMock()
        mcp_repository.list_mcp_server_configs.return_value = [{"id": 42}]
        mcp_repository.get_mcp_server_config.return_value = {"id": 42}
        mcp_repository.create_mcp_server_config.return_value = {"id": 42}
        mcp_repository.update_mcp_server_config.return_value = {"id": 42}
        mcp_repository.delete_mcp_server_config.return_value = True
        mcp_repository.update_mcp_server_test_result.return_value = {"id": 42}
        repository._mcp_server_configs = mcp_repository
        payload = {"server_key": "example"}
        result = {"status": "succeeded"}

        repository._seed_default_mcp_server_configs()
        self.assertEqual(repository.list_mcp_server_configs(), [{"id": 42}])
        self.assertEqual(repository.get_mcp_server_config(42), {"id": 42})
        self.assertEqual(repository.create_mcp_server_config(payload), {"id": 42})
        self.assertEqual(
            repository.update_mcp_server_config(42, payload),
            {"id": 42},
        )
        self.assertTrue(repository.delete_mcp_server_config(42))
        self.assertEqual(
            repository.update_mcp_server_test_result(42, result),
            {"id": 42},
        )

        mcp_repository._seed_default_mcp_server_configs.assert_called_once_with()
        mcp_repository.list_mcp_server_configs.assert_called_once_with()
        mcp_repository.get_mcp_server_config.assert_called_once_with(42)
        mcp_repository.create_mcp_server_config.assert_called_once_with(payload)
        mcp_repository.update_mcp_server_config.assert_called_once_with(42, payload)
        mcp_repository.delete_mcp_server_config.assert_called_once_with(42)
        mcp_repository.update_mcp_server_test_result.assert_called_once_with(
            42,
            result,
        )

    def test_mcp_access_token_compatibility_methods_delegate_to_component(self) -> None:
        repository = MySQLRepository(database=MagicMock(spec=DatabaseLifecycle))
        token_repository = MagicMock()
        token_repository.create_user_mcp_token.return_value = {
            "token_metadata": {"id": 42},
            "replaced_count": 0,
        }
        token_repository.list_user_mcp_tokens.return_value = [{"id": 42}]
        token_repository.get_user_by_mcp_token_hash.return_value = {"user_id": 7}
        token_repository.delete_user_mcp_token.return_value = True
        repository._mcp_access_tokens = token_repository

        created = repository.create_user_mcp_token(
            user_id=7,
            token_hash="digest",
            token_hint="aigc_mcp_abc...wxyz",
            scopes=["projects:favorites:read"],
            client_type="claude",
            client_label="Desktop",
            expires_at="2026-08-01T00:00:00Z",
        )

        self.assertEqual(created["token_metadata"], {"id": 42})
        self.assertEqual(repository.list_user_mcp_tokens(user_id=7), [{"id": 42}])
        self.assertEqual(
            repository.get_user_by_mcp_token_hash("digest"),
            {"user_id": 7},
        )
        self.assertTrue(repository.delete_user_mcp_token(user_id=7, token_id=42))
        token_repository.create_user_mcp_token.assert_called_once_with(
            user_id=7,
            token_hash="digest",
            token_hint="aigc_mcp_abc...wxyz",
            scopes=["projects:favorites:read"],
            client_type="claude",
            client_label="Desktop",
            expires_at="2026-08-01T00:00:00Z",
        )
        token_repository.list_user_mcp_tokens.assert_called_once_with(user_id=7)
        token_repository.get_user_by_mcp_token_hash.assert_called_once_with("digest")
        token_repository.delete_user_mcp_token.assert_called_once_with(
            user_id=7,
            token_id=42,
        )

    def test_user_account_compatibility_methods_delegate_to_component(self) -> None:
        repository = MySQLRepository(database=MagicMock(spec=DatabaseLifecycle))
        account_repository = MagicMock()
        account_repository.get_user_count.return_value = 10
        account_repository.get_today_registered_user_count.return_value = 2
        account_repository.get_user_by_phone.return_value = {"id": 41}
        account_repository.get_user_by_email.return_value = {"id": 42}
        account_repository.create_user.return_value = 43
        account_repository.update_user_password.return_value = 1
        account_repository.create_user_with_email.return_value = 44
        repository._user_accounts = account_repository

        self.assertEqual(repository.get_user_count(), 10)
        self.assertEqual(repository.get_today_registered_user_count(), 2)
        self.assertEqual(repository.get_user_by_phone("13800000000"), {"id": 41})
        self.assertEqual(
            repository.get_user_by_email("reader@example.com"),
            {"id": 42},
        )
        self.assertEqual(repository.create_user("phone", "reader", "hash"), 43)
        self.assertEqual(
            repository.update_user_password(
                user_id=42,
                email="reader@example.com",
                hashed_password="new-hash",
            ),
            1,
        )
        self.assertEqual(
            repository.create_user_with_email("reader@example.com", "hash"),
            44,
        )

        account_repository.get_user_count.assert_called_once_with()
        account_repository.get_today_registered_user_count.assert_called_once_with()
        account_repository.get_user_by_phone.assert_called_once_with("13800000000")
        account_repository.get_user_by_email.assert_called_once_with(
            "reader@example.com"
        )
        account_repository.create_user.assert_called_once_with(
            "phone",
            "reader",
            "hash",
            "user",
        )
        account_repository.update_user_password.assert_called_once_with(
            user_id=42,
            email="reader@example.com",
            hashed_password="new-hash",
        )
        account_repository.create_user_with_email.assert_called_once_with(
            "reader@example.com",
            "hash",
            "",
            "user",
            "",
        )

    def test_subscription_compatibility_methods_delegate_to_component(self) -> None:
        repository = MySQLRepository(database=MagicMock(spec=DatabaseLifecycle))
        subscription_repository = MagicMock()
        subscription_repository.upsert_briefing_subscription.return_value = {"id": 42}
        subscription_repository.cancel_briefing_subscription.return_value = True
        subscription_repository.get_user_briefing_subscriptions.return_value = [
            {"id": 42}
        ]
        subscription_repository.get_active_subscribers.return_value = [
            {"email": "reader@example.com"}
        ]
        repository._briefing_subscriptions = subscription_repository

        self.assertEqual(
            repository.upsert_briefing_subscription(
                7,
                "reader@example.com",
                "github",
                "weekly",
            ),
            {"id": 42},
        )
        self.assertTrue(
            repository.cancel_briefing_subscription(7, "github", "weekly")
        )
        self.assertEqual(
            repository.get_user_briefing_subscriptions(7),
            [{"id": 42}],
        )
        self.assertEqual(
            repository.get_active_subscribers("github", "weekly"),
            [{"email": "reader@example.com"}],
        )

        subscription_repository.upsert_briefing_subscription.assert_called_once_with(
            7,
            "reader@example.com",
            "github",
            "weekly",
        )
        subscription_repository.cancel_briefing_subscription.assert_called_once_with(
            7,
            "github",
            "weekly",
        )
        subscription_repository.get_user_briefing_subscriptions.assert_called_once_with(7)
        subscription_repository.get_active_subscribers.assert_called_once_with(
            "github",
            "weekly",
        )

    @staticmethod
    def _repository_with_database():
        cursor = MagicMock()
        cursor_context = MagicMock()
        cursor_context.__enter__.return_value = cursor
        connection = MagicMock()
        connection.cursor.return_value = cursor_context
        pool = MagicMock()
        pool.connection.return_value = connection
        database = DatabaseLifecycle(MagicMock(return_value=pool))
        repository = MySQLRepository(database=database)
        return repository, connection, cursor


if __name__ == "__main__":
    unittest.main()
