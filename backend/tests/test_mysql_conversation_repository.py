from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from backend.app.core.database import DatabaseLifecycle
from backend.app.repositories.mysql_conversation_repository import MySQLConversationRepository


class MySQLConversationRepositoryTests(unittest.TestCase):
    def test_context_read_is_owner_scoped_and_touched_in_one_transaction(self) -> None:
        repository, database, _, cursor = self._transaction_repository()
        cursor.fetchone.side_effect = [
            {"id": 7, "user_id": 3},
            {"id": 7, "user_id": 3},
        ]
        cursor.fetchall.return_value = [
            {
                "id": 11,
                "conversation_id": 7,
                "content": "hello",
                "thinking": "trace",
                "sources_json": "[]",
                "attachments_json": "[]",
                "status": "done",
            }
        ]

        result = repository.get_owned_conversation_context(
            user_id=3,
            conversation_id=7,
        )

        self.assertEqual(result["conversation"]["user_id"], 3)
        self.assertEqual(result["messages"][0]["thinking_preview"], "trace")
        owner_sql, owner_params = cursor.execute.call_args_list[0].args
        self.assertIn("id = %s AND user_id = %s", owner_sql)
        self.assertEqual(owner_params, (7, 3))
        self.assertTrue(
            any("SET last_accessed_at = NOW()" in call.args[0] for call in cursor.execute.call_args_list)
        )
        database.transaction.assert_called_once_with()
        database.connection.assert_not_called()

    def test_foreign_conversation_delete_is_indistinguishable_and_non_mutating(self) -> None:
        repository, database, _, cursor = self._transaction_repository()
        cursor.fetchone.return_value = None

        result = repository.delete_owned_conversation(user_id=3, conversation_id=9)

        self.assertFalse(result)
        self.assertEqual(len(cursor.execute.call_args_list), 1)
        sql, params = cursor.execute.call_args.args
        self.assertIn("user_id = %s FOR UPDATE", sql)
        self.assertEqual(params, (9, 3))
        database.transaction.assert_called_once_with()

    def test_append_pair_uses_one_transaction_and_preserves_shapes(self) -> None:
        repository, database, _, cursor = self._transaction_repository()
        conversation = {"id": 7, "user_id": 3, "title": "Question"}
        user_row = {
            "id": 11,
            "conversation_id": 7,
            "content": "Question",
            "thinking": "",
            "sources_json": "[]",
            "attachments_json": '[{"id": "a"}]',
            "status": "done",
        }
        assistant_row = {
            "id": 12,
            "conversation_id": 7,
            "content": "Answer",
            "thinking": "Reasoning",
            "sources_json": '[{"id": "doc"}]',
            "attachments_json": '[{"id": "a"}]',
            "status": "done",
        }
        cursor.fetchone.side_effect = [
            conversation,
            user_row,
            assistant_row,
            {"cnt": 2},
            {"cnt": 2},
            {"content": "Answer"},
            {"content": "Question"},
            conversation,
        ]
        cursor.fetchall.side_effect = [
            [{"id": 12}, {"id": 11}],
            [{"id": 7}],
            [user_row, assistant_row],
        ]

        result = repository.append_message_pair(
            user_id=3,
            conversation_id=None,
            scope="global",
            scope_key=None,
            user_message="Question",
            assistant_content="Answer",
            assistant_thinking="Reasoning",
            sources=[{"id": "doc"}],
            attachments=[{"id": "a"}],
        )

        inserts = [
            call for call in cursor.execute.call_args_list if "INSERT INTO chat_messages" in call.args[0]
        ]
        self.assertEqual(len(inserts), 2)
        self.assertEqual(result["user_message"]["attachments"], [{"id": "a"}])
        self.assertEqual(result["assistant_message"]["sources"], [{"id": "doc"}])
        self.assertEqual(result["assistant_message"]["thinking_preview"], "Reasoning")
        self.assertEqual([message["id"] for message in result["messages"]], [11, 12])
        database.transaction.assert_called_once_with()
        database.connection.assert_not_called()

    def test_owned_suffix_delete_and_stats_share_transaction(self) -> None:
        repository, database, _, cursor = self._transaction_repository()
        target = {
            "id": 11,
            "conversation_id": 7,
            "created_at": "2026-07-23T10:00:00",
            "content": "Question",
            "thinking": "",
            "sources_json": "[]",
            "attachments_json": "[]",
            "status": "done",
        }
        cursor.fetchone.side_effect = [
            target,
            {"cnt": 0},
            None,
            None,
            {"id": 7, "user_id": 3},
        ]
        cursor.fetchall.side_effect = [[{"id": 11}, {"id": 12}], []]

        result = repository.prepare_owned_regeneration(user_id=3, message_id=11)

        self.assertEqual(result["deleted_ids"], [11, 12])
        self.assertEqual(result["target_message"]["id"], 11)
        first_sql, first_params = cursor.execute.call_args_list[0].args
        self.assertIn("c.user_id = %s", first_sql)
        self.assertIn("FOR UPDATE", first_sql)
        self.assertEqual(first_params, (11, 3))
        self.assertTrue(any("UPDATE conversations" in call.args[0] for call in cursor.execute.call_args_list))
        database.transaction.assert_called_once_with()

    def test_daily_quota_preserves_cst_conversion(self) -> None:
        repository, database, _, cursor = self._connection_repository()
        cursor.fetchone.return_value = {"cnt": 6}

        result = repository.count_user_messages_today(3)

        self.assertEqual(result, 6)
        sql, params = cursor.execute.call_args.args
        self.assertIn("CONVERT_TZ(m.created_at, '+00:00', '+08:00')", sql)
        self.assertIn("UTC_TIMESTAMP()", sql)
        self.assertEqual(params, (3,))
        database.connection.assert_called_once_with()
        database.transaction.assert_not_called()

    def test_cleanup_is_bounded_oldest_first_transaction(self) -> None:
        repository, database, _, cursor = self._transaction_repository()
        cursor.fetchall.return_value = [{"id": 1}, {"id": 2}]
        cursor.rowcount = 2

        result = repository.cleanup_stale_conversations(stale_days=7, limit=5)

        self.assertEqual(result, 2)
        select_sql, select_params = cursor.execute.call_args_list[0].args
        self.assertIn("ORDER BY last_accessed_at ASC, updated_at ASC, id ASC", select_sql)
        self.assertIn("FOR UPDATE", select_sql)
        self.assertEqual(select_params, (7, 5))
        database.transaction.assert_called_once_with()

    @staticmethod
    def _transaction_repository():
        database = MagicMock(spec=DatabaseLifecycle)
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        database.transaction.return_value.__enter__.return_value = connection
        return MySQLConversationRepository(database), database, connection, cursor

    @staticmethod
    def _connection_repository():
        database = MagicMock(spec=DatabaseLifecycle)
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        database.connection.return_value.__enter__.return_value = connection
        return MySQLConversationRepository(database), database, connection, cursor


if __name__ == "__main__":
    unittest.main()
