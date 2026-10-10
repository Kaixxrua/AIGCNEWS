import asyncio
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from backend.app.repositories.postgres_ai_ops_diagnostics_repository import PostgresAiOpsDiagnosticsRepository
from backend.app.repositories.postgres_ingestion_task_repository import PostgresIngestionTaskRepository
from backend.app.repositories.postgres_x_translation_repository import PostgresXTranslationTaskRepository
from backend.app.services.ai_ops import create_ai_ops_service
from backend.tests.postgres_test_safety import postgres_test_sandbox


def test_diagnostics_project_errors_and_compare_source_windows_without_secret_text():
    with postgres_test_sandbox() as sandbox:
        db = sandbox.database
        repo = PostgresAiOpsDiagnosticsRepository(db)
        now = datetime.now(timezone.utc)
        with db.transaction() as conn:
            for age in (1, 2, 26):
                conn.execute("INSERT INTO error_events (occurred_at,level,logger_name,message) "
                             "VALUES (%s,'ERROR','backend.app.services.ingestion.arxiv_pdf_downloader','HTTP 429 SECRET')",
                             (now-timedelta(hours=age),))
            for status, age, count in (("success", 1, 10), ("failed", 2, 0), ("failed", 30, 0)):
                at = (now-timedelta(hours=age)).isoformat()
                conn.execute("INSERT INTO ingestion_tasks (task_name,status,item_count,started_at,finished_at,error_msg) "
                             "VALUES ('single:x',%s,%s,%s,%s,'SECRET')", (status, count, at, at))
            conn.execute("INSERT INTO ingestion_tasks (task_name,status,started_at) VALUES ('single:x','failed','9999-bad')")
        errors = repo.errors()
        assert errors["total"] == 2 and errors["groups"][0]["sample_count"] == 2
        assert errors["groups"][0]["category"] == "rate_limit" and "SECRET" not in str(errors)
        [source] = repo.source_trends()["sources"]
        assert source["total_24h"] == 2 and source["failed_24h"] == 1
        assert source["failed_previous_24h"] == 1 and source["items_24h"] == 10
        assert source["last_success_in_window"] == now-timedelta(hours=1)
        assert "SECRET" not in str(source)
        status = repo.database_status()
        assert "query" not in status and status["connections"] >= 0
        assert repo.investigation_history()["failures"] == []


def test_full_investigation_uses_real_diagnostics_and_persistence_with_one_model_call():
    with postgres_test_sandbox() as sandbox:
        db = sandbox.database
        with db.transaction() as conn:
            conn.execute("INSERT INTO error_events (level,logger_name,message,exception_type) VALUES "
                         "('ERROR','backend.app.api.exception_handlers','statement timeout TOKEN=secret','QueryCanceled')")
        repositories = SimpleNamespace(ingestion_tasks=PostgresIngestionTaskRepository(db),
                                       x_translation_tasks=PostgresXTranslationTaskRepository(db))
        model = SimpleNamespace(ainvoke=AsyncMock(return_value=SimpleNamespace(content="有限结论")))
        provider = MagicMock()
        provider.get_chat_model.return_value.model_copy.return_value = model
        health, scheduler = MagicMock(), MagicMock()
        health.run.return_value = {"status": "ok"}
        scheduler.running, scheduler.state = True, 0
        scheduler.get_jobs.return_value = []
        svc = create_ai_ops_service(database=db, repositories=repositories, health_checks=health,
                                    scheduler=scheduler, model_provider=provider)
        run = svc.repository.create("manual")
        asyncio.run(svc.run(run))
        result = svc.repository.get(run)
        assert result["status"] == "completed" and result["report"] == "有限结论"
        assert model.ainvoke.call_count == 1
        prompt = model.ainvoke.call_args.args[0][-1].content
        assert "TOKEN" not in prompt and "secret" not in prompt
        evidence = json.loads(prompt)
        assert evidence["errors"]["result"]["groups"][0]["category"] == "query_timeout"
        assert [book["id"] for book in evidence["knowledge"]["result"]["runbooks"]] == ["database"]
        assert len([event for event in result["events"] if event["kind"] == "tool_result"]) == 11
