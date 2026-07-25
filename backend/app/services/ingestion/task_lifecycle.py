from __future__ import annotations

from backend.app.repositories.task_repository import IngestionTaskWriter


class IngestionTaskLifecycle:
    """Adapt ingestion orchestration to the task writer contract."""

    def __init__(self, writer: IngestionTaskWriter) -> None:
        self.writer = writer

    def start(self, task_name: str) -> int:
        return self.writer.create_task(task_name)

    def succeed(self, task_id: int, item_count: int) -> None:
        self.writer.finish_task(
            task_id,
            status="success",
            error_msg=None,
            item_count=item_count,
        )

    def fail(self, task_id: int, error: Exception) -> None:
        self.writer.finish_task(
            task_id,
            status="failed",
            error_msg=str(error),
            item_count=0,
        )
