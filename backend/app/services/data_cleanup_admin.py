from __future__ import annotations

"""Destructive administrative cleanup orchestration."""

import asyncio
import logging
from typing import Protocol

from backend.app.repositories.document_repository import DocumentAdminWriter
from backend.app.repositories.task_repository import IngestionTaskAdminRepository

logger = logging.getLogger(__name__)


class VectorCollectionAdmin(Protocol):
    def drop_collection(self) -> bool: ...


class DataCleanupAdminService:
    """Clear relational records before attempting vector collection cleanup."""

    def __init__(
        self,
        documents: DocumentAdminWriter,
        tasks: IngestionTaskAdminRepository,
        vector_collection: VectorCollectionAdmin,
    ) -> None:
        self._documents = documents
        self._tasks = tasks
        self._vector_collection = vector_collection

    async def clear_all(self) -> dict[str, int | bool]:
        deleted_documents = await asyncio.to_thread(
            self._documents.clear_all_documents
        )
        deleted_tasks = await asyncio.to_thread(self._tasks.clear_all_tasks)
        logger.info(
            "[Ops] 已清空关系数据：documents=%d, tasks=%d",
            deleted_documents,
            deleted_tasks,
        )

        vector_dropped = False
        try:
            vector_dropped = await asyncio.to_thread(
                self._vector_collection.drop_collection
            )
            logger.info("[Ops] Milvus 集合已删除：%s", vector_dropped)
        except Exception as exc:
            logger.warning("[Ops] Milvus 清空失败（可能尚未初始化）：%s", exc)

        return {
            "deleted_documents": deleted_documents,
            "deleted_tasks": deleted_tasks,
            "vector_dropped": vector_dropped,
        }
