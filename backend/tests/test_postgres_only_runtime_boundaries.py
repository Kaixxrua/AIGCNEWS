from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"


def test_production_runtime_imports_no_mysql_modules() -> None:
    script = """
import json
import sys

import backend.app.main
import backend.app.api.dependencies
import backend.app.core.scheduler
import backend.app.repositories.application_repository_factory
import backend.app.repositories.project_catalog_factory

blocked = sorted(
    name
    for name in sys.modules
    if name == "pymysql"
    or name.startswith("pymysql.")
    or name == "DBUtils"
    or name.startswith("DBUtils.")
    or name == "backend.app.core.database"
    or name.startswith("backend.app.repositories.mysql_")
    or name == "backend.app.repositories.mysql_repo"
)
print(json.dumps(blocked))
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(completed.stdout) == []


def test_production_image_excludes_migration_dependencies() -> None:
    requirements = (BACKEND / "requirements.txt").read_text(encoding="utf-8").lower()
    dockerfile = (BACKEND / "Dockerfile").read_text(encoding="utf-8").lower()

    assert "pymysql" not in requirements
    assert "dbutils" not in requirements
    assert "requirements-migration.txt" not in dockerfile
