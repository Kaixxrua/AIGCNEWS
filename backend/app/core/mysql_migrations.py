from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from backend.app.core.database import DatabaseLifecycle, mysql_database


MIGRATION_FILE_RE = re.compile(r"^(?P<version>\d{4})_(?P<name>[a-z0-9][a-z0-9_]*)\.sql$")
DEFAULT_MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations" / "mysql"
MIGRATION_LOCK_NAME = "aigcnews:project_catalog:mysql_migrations"


class MySQLMigrationError(RuntimeError):
    """Raised when MySQL migration history or files are unsafe to apply."""


@dataclass(frozen=True)
class MySQLMigration:
    version: int
    filename: str
    checksum: str
    sql: str


@dataclass(frozen=True)
class MySQLMigrationStatus:
    version: int
    filename: str
    checksum: str
    applied: bool


def discover_mysql_migrations(
    directory: Path | str = DEFAULT_MIGRATIONS_DIR,
) -> list[MySQLMigration]:
    root = Path(directory)
    files = sorted(path for path in root.iterdir() if path.is_file() and path.suffix == ".sql")
    migrations: list[MySQLMigration] = []
    seen_versions: set[int] = set()
    for path in files:
        match = MIGRATION_FILE_RE.fullmatch(path.name)
        if match is None:
            raise MySQLMigrationError(
                f"invalid MySQL migration filename {path.name!r}; expected 0001_name.sql"
            )
        version = int(match.group("version"))
        if version == 0 or version in seen_versions:
            raise MySQLMigrationError("MySQL migration versions must be unique and start at 0001")
        seen_versions.add(version)
        payload = path.read_bytes()
        migrations.append(
            MySQLMigration(
                version=version,
                filename=path.name,
                checksum=hashlib.sha256(payload).hexdigest(),
                sql=payload.decode("utf-8"),
            )
        )
    actual = [migration.version for migration in migrations]
    if actual != list(range(1, len(migrations) + 1)):
        raise MySQLMigrationError("MySQL migration versions must be contiguous from 0001")
    return migrations


class MySQLMigrationRunner:
    """Validate and apply explicit MySQL migrations under a named lock."""

    def __init__(
        self,
        database: DatabaseLifecycle = mysql_database,
        *,
        migrations_dir: Path | str = DEFAULT_MIGRATIONS_DIR,
        lock_name: str = MIGRATION_LOCK_NAME,
    ) -> None:
        self._database = database
        self._migrations_dir = Path(migrations_dir)
        self._lock_name = lock_name

    def status(self) -> list[MySQLMigrationStatus]:
        migrations = discover_mysql_migrations(self._migrations_dir)
        with self._database.connection() as connection:
            self._lock(connection)
            try:
                self._ensure_ledger(connection)
                applied = self._read_applied(connection)
                self._validate_history(migrations, applied)
                return [
                    MySQLMigrationStatus(
                        migration.version,
                        migration.filename,
                        migration.checksum,
                        migration.version in applied,
                    )
                    for migration in migrations
                ]
            finally:
                self._unlock(connection)

    def apply(self) -> list[MySQLMigration]:
        migrations = discover_mysql_migrations(self._migrations_dir)
        applied_now: list[MySQLMigration] = []
        with self._database.connection() as connection:
            self._lock(connection)
            try:
                self._ensure_ledger(connection)
                applied = self._read_applied(connection)
                self._validate_history(migrations, applied)
                for migration in migrations:
                    if migration.version in applied:
                        continue
                    try:
                        with connection.cursor() as cursor:
                            cursor.execute(migration.sql)
                            cursor.execute(
                                """
                                INSERT INTO app_mysql_schema_migrations
                                    (version, filename, checksum_sha256)
                                VALUES (%s, %s, %s)
                                """,
                                (migration.version, migration.filename, migration.checksum),
                            )
                        connection.commit()
                    except BaseException:
                        connection.rollback()
                        raise
                    applied_now.append(migration)
                return applied_now
            finally:
                self._unlock(connection)

    def _lock(self, connection: Any) -> None:
        with connection.cursor() as cursor:
            cursor.execute("SELECT GET_LOCK(%s, 10) AS acquired", (self._lock_name,))
            row = cursor.fetchone()
        acquired = row.get("acquired") if isinstance(row, dict) else row[0]
        if int(acquired or 0) != 1:
            raise MySQLMigrationError("could not acquire MySQL migration lock")

    def _unlock(self, connection: Any) -> None:
        with connection.cursor() as cursor:
            cursor.execute("SELECT RELEASE_LOCK(%s)", (self._lock_name,))

    @staticmethod
    def _ensure_ledger(connection: Any) -> None:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS app_mysql_schema_migrations (
                    version INT NOT NULL PRIMARY KEY,
                    filename VARCHAR(255) NOT NULL UNIQUE,
                    checksum_sha256 CHAR(64) NOT NULL,
                    applied_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )
        connection.commit()

    @staticmethod
    def _read_applied(connection: Any) -> dict[int, tuple[str, str]]:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT version, filename, checksum_sha256
                FROM app_mysql_schema_migrations
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
            result[version] = (filename, checksum)
        return result

    @staticmethod
    def _validate_history(
        migrations: list[MySQLMigration],
        applied: dict[int, tuple[str, str]],
    ) -> None:
        versions = sorted(applied)
        if versions != list(range(1, len(versions) + 1)):
            raise MySQLMigrationError("applied MySQL migration history contains a version gap")
        by_version = {migration.version: migration for migration in migrations}
        for version, (filename, checksum) in applied.items():
            migration = by_version.get(version)
            if migration is None:
                raise MySQLMigrationError(
                    f"applied MySQL migration {version:04d} has no local SQL file"
                )
            if migration.filename != filename or migration.checksum != checksum.lower():
                raise MySQLMigrationError(
                    f"MySQL migration {version:04d} filename or checksum drift detected"
                )
