from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from backend.app.core.postgres_database import (
    PostgresDatabaseLifecycle,
    postgres_database,
)

MIGRATION_FILE_RE = re.compile(r"^(?P<version>\d{4})_(?P<name>[a-z0-9][a-z0-9_]*)\.sql$")
DEFAULT_MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations" / "postgres"
ADVISORY_LOCK_ID = 6_684_656_731_273_528_001
logger = logging.getLogger(__name__)


class MigrationError(RuntimeError):
    """Raised when migration history or files are unsafe to apply."""


@dataclass(frozen=True)
class Migration:
    version: int
    filename: str
    checksum: str
    sql: str


@dataclass(frozen=True)
class MigrationStatus:
    version: int
    filename: str
    checksum: str
    applied: bool


def discover_migrations(directory: Path | str = DEFAULT_MIGRATIONS_DIR) -> list[Migration]:
    root = Path(directory)
    files = sorted(path for path in root.iterdir() if path.is_file() and path.suffix == ".sql")
    migrations: list[Migration] = []
    seen_versions: set[int] = set()

    for path in files:
        match = MIGRATION_FILE_RE.fullmatch(path.name)
        if match is None:
            raise MigrationError(
                f"invalid PostgreSQL migration filename {path.name!r}; expected 0001_name.sql"
            )
        version = int(match.group("version"))
        if version == 0:
            raise MigrationError("PostgreSQL migration versions must start at 0001")
        if version in seen_versions:
            raise MigrationError(f"duplicate PostgreSQL migration version {version:04d}")
        seen_versions.add(version)
        payload = path.read_bytes()
        migrations.append(
            Migration(
                version=version,
                filename=path.name,
                checksum=hashlib.sha256(payload).hexdigest(),
                sql=payload.decode("utf-8"),
            )
        )

    expected = list(range(1, len(migrations) + 1))
    actual = [migration.version for migration in migrations]
    if actual != expected:
        raise MigrationError(
            "PostgreSQL migration versions must be contiguous from 0001; "
            f"found {', '.join(f'{version:04d}' for version in actual) or 'none'}"
        )
    return migrations


class PostgresMigrationRunner:
    """Validate and apply explicit PostgreSQL migrations under a session lock."""

    def __init__(
        self,
        database: PostgresDatabaseLifecycle = postgres_database,
        *,
        migrations_dir: Path | str = DEFAULT_MIGRATIONS_DIR,
        advisory_lock_id: int = ADVISORY_LOCK_ID,
    ) -> None:
        self._database = database
        self._migrations_dir = Path(migrations_dir)
        self._advisory_lock_id = advisory_lock_id

    def status(self) -> list[MigrationStatus]:
        migrations = discover_migrations(self._migrations_dir)
        with self._database.connection() as connection:
            self._lock(connection)
            try:
                self._ensure_ledger(connection)
                applied = self._read_applied(connection)
                self._validate_history(migrations, applied)
                result = [
                    MigrationStatus(
                        version=migration.version,
                        filename=migration.filename,
                        checksum=migration.checksum,
                        applied=migration.version in applied,
                    )
                    for migration in migrations
                ]
            except BaseException:
                try:
                    self._unlock(connection)
                except BaseException:
                    logger.exception("Failed to release PostgreSQL migration advisory lock")
                raise
            else:
                self._unlock(connection)
                return result

    def apply(self) -> list[Migration]:
        migrations = discover_migrations(self._migrations_dir)
        applied_now: list[Migration] = []
        with self._database.connection() as connection:
            self._lock(connection)
            try:
                self._ensure_ledger(connection)
                applied = self._read_applied(connection)
                self._validate_history(migrations, applied)
                for migration in migrations:
                    if migration.version in applied:
                        continue
                    with connection.transaction():
                        with connection.cursor() as cursor:
                            cursor.execute(migration.sql)
                            cursor.execute(
                                """
                                INSERT INTO app_schema_migrations
                                    (version, filename, checksum_sha256)
                                VALUES (%s, %s, %s)
                                """,
                                (migration.version, migration.filename, migration.checksum),
                            )
                    applied_now.append(migration)
            except BaseException:
                try:
                    self._unlock(connection)
                except BaseException:
                    logger.exception("Failed to release PostgreSQL migration advisory lock")
                raise
            else:
                self._unlock(connection)
                return applied_now

    def _lock(self, connection: Any) -> None:
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_lock(%s)", (self._advisory_lock_id,))

    def _unlock(self, connection: Any) -> None:
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_unlock(%s)", (self._advisory_lock_id,))

    @staticmethod
    def _ensure_ledger(connection: Any) -> None:
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS app_schema_migrations (
                        version INTEGER PRIMARY KEY CHECK (version > 0),
                        filename TEXT NOT NULL UNIQUE,
                        checksum_sha256 CHAR(64) NOT NULL,
                        applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )

    @staticmethod
    def _read_applied(connection: Any) -> dict[int, tuple[str, str]]:
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT version, filename, checksum_sha256
                    FROM app_schema_migrations
                    ORDER BY version
                    """
                )
                rows: Iterable[Any] = cursor.fetchall()
        result: dict[int, tuple[str, str]] = {}
        for row in rows:
            if isinstance(row, dict):
                version = int(row["version"])
                filename = str(row["filename"])
                checksum = str(row["checksum_sha256"])
            else:
                version = int(row[0])
                filename = str(row[1])
                checksum = str(row[2])
            if version in result:
                raise MigrationError(f"duplicate applied PostgreSQL migration version {version:04d}")
            result[version] = (filename, checksum)
        return result

    @staticmethod
    def _validate_history(
        migrations: list[Migration], applied: dict[int, tuple[str, str]]
    ) -> None:
        by_version = {migration.version: migration for migration in migrations}
        applied_versions = sorted(applied)
        if applied_versions != list(range(1, len(applied_versions) + 1)):
            raise MigrationError("applied PostgreSQL migration history contains a version gap")
        for version, (filename, checksum) in applied.items():
            migration = by_version.get(version)
            if migration is None:
                raise MigrationError(
                    f"applied PostgreSQL migration {version:04d} has no local SQL file"
                )
            if filename != migration.filename:
                raise MigrationError(
                    f"PostgreSQL migration {version:04d} filename drift: "
                    f"ledger has {filename!r}, local file is {migration.filename!r}"
                )
            if checksum.lower() != migration.checksum:
                raise MigrationError(
                    f"PostgreSQL migration {version:04d} checksum drift detected"
                )


def pending_migration_labels(
    runner: PostgresMigrationRunner | None = None,
) -> list[str]:
    """未应用迁移的文件名列表（如 ["0030_user_foreign_keys.sql"]）。

    供启动自检告警使用：代码先行、迁移未跑时（如 uq_briefings_date 缺失
    导致简报 ON CONFLICT 保存全线失败），让滞后状态在启动日志里可见。
    台账校验失败（版本空洞/校验和漂移）按 MigrationError 上抛。
    """
    runner = runner or PostgresMigrationRunner()
    return [status.filename for status in runner.status() if not status.applied]
