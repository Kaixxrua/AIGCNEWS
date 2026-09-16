from __future__ import annotations

import json
from typing import Any

from backend.app.core.postgres_database import PostgresDatabaseLifecycle
from backend.app.monitoring.mcp_tools import DSH_PLUGIN_CLIENT


class PostgresMcpMetricsCheckpointRepository:
    """Durable singleton checkpoint for the Redis MCP metrics aggregate."""

    def __init__(self, database: PostgresDatabaseLifecycle) -> None:
        self._database = database

    def load(self) -> dict[str, Any] | None:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT snapshot FROM mcp_metrics_checkpoint WHERE id = 1"
                )
                row = cursor.fetchone()
        if not row:
            return None
        payload = row["snapshot"]
        if isinstance(payload, str):
            payload = json.loads(payload)
        return dict(payload)

    def save_if_not_older(self, snapshot: dict[str, Any]) -> bool:
        total_calls = int(snapshot.get("total_calls", 0))
        clients = snapshot.get("clients")
        dsh_entry = clients.get(DSH_PLUGIN_CLIENT) if isinstance(clients, dict) else None
        dsh_calls = int(dsh_entry.get("calls", 0)) if isinstance(dsh_entry, dict) else 0
        if total_calls < 0 or dsh_calls < 0 or dsh_calls > total_calls:
            raise ValueError("invalid MCP metrics checkpoint counters")
        encoded = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"))

        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO mcp_metrics_checkpoint
                        (id, total_calls, dsh_calls, snapshot, updated_at)
                    VALUES (1, %s, %s, %s::jsonb, CURRENT_TIMESTAMP)
                    ON CONFLICT (id) DO UPDATE SET
                        total_calls = EXCLUDED.total_calls,
                        dsh_calls = EXCLUDED.dsh_calls,
                        snapshot = EXCLUDED.snapshot,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE EXCLUDED.total_calls >= mcp_metrics_checkpoint.total_calls
                      AND EXCLUDED.dsh_calls >= mcp_metrics_checkpoint.dsh_calls
                    RETURNING id
                    """,
                    (total_calls, dsh_calls, encoded),
                )
                row = cursor.fetchone()
        return row is not None
