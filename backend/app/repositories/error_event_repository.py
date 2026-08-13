from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol, Sequence


@dataclass(frozen=True)
class ErrorEventInsert:
    """一条待写入的后端错误事件。

    occurred_at 为 None 时由数据库 DEFAULT CURRENT_TIMESTAMP 兜底；
    message/stack_trace 的长度截断发生在采集层（ErrorEventCapture），
    仓储不做二次截断。
    """

    level: str
    logger_name: str
    message: str
    exception_type: str | None = None
    stack_trace: str | None = None
    occurred_at: datetime | None = None


class ErrorEventWriter(Protocol):
    def insert_events(self, events: Sequence[ErrorEventInsert]) -> int: ...

    def prune_older_than(self, cutoff: datetime) -> int: ...


class ErrorEventReader(Protocol):
    def list_events(self, page: int = 1, page_size: int = 10) -> dict[str, Any]: ...


class ErrorEventRepository(ErrorEventWriter, ErrorEventReader, Protocol):
    """Persistence boundary for backend error events."""
