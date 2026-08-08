"""scripts/verify_postgres_application_restore.sh 双模式契约测试。

通过 PATH 注入桩 psql 回放账本/表存在性应答，不触碰真实数据库：
  - 默认模式（备份前 / 恢复后）：账本连续 + 必需表存在即可，
    不与仓库最新 migration 比对（迁移前必能备份、恢复旧备份不误判）；
  - --strict / POSTGRES_VERIFY_STRICT=1：恢复旧的严格口径，
    账本必须恰好覆盖到仓库最新 migration 且文件名一致。
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
VERIFY = REPO_ROOT / "scripts" / "verify_postgres_application_restore.sh"

# 桩 psql：按查询内容回放 LEDGER_STATE / LATEST_NAME / MISSING_TABLE 控制的应答；
# heredoc smoke（无 --command）直接消费 stdin 成功退出。
STUB_PSQL = """\
#!/usr/bin/env python3
import os
import sys

command = ""
args = sys.argv[1:]
for index, arg in enumerate(args):
    if arg.startswith("--command="):
        command = arg.split("=", 1)[1]
    elif arg == "--command" and index + 1 < len(args):
        command = args[index + 1]

if not command:
    sys.exit(0)

missing_table = os.environ.get("MISSING_TABLE", "")
if "to_regclass('public.app_schema_migrations')" in command:
    print(0 if missing_table == "app_schema_migrations" else 1)
elif "to_regclass(" in command:
    table = command.split("to_regclass('public.", 1)[1].split("'", 1)[0]
    print(0 if table == missing_table else 1)
elif "COALESCE(MIN(version)" in command:
    print(os.environ["LEDGER_STATE"])
elif "generate_series" in command:
    print(os.environ.get("CONTIGUOUS", "1"))
elif "SELECT filename FROM public.app_schema_migrations" in command:
    print(os.environ.get("LATEST_NAME", ""))
else:
    print(1)
"""


def _make_migrations_dir(tmp_path: Path, versions: list[int]) -> Path:
    directory = tmp_path / "migrations"
    directory.mkdir()
    for version in versions:
        (directory / f"{version:04d}_migration_{version}.sql").write_text("-- stub\n")
    return directory


def _run_verify(
    tmp_path: Path,
    *,
    ledger_state: str = "1|5|5",
    contiguous: str = "1",
    latest_name: str = "0005_migration_5.sql",
    missing_table: str = "",
    migration_versions: list[int] | None = None,
    extra_args: list[str] | None = None,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    stub = bin_dir / "psql"
    stub.write_text(STUB_PSQL)
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}{os.pathsep}{env['PATH']}",
            "LEDGER_STATE": ledger_state,
            "CONTIGUOUS": contiguous,
            "LATEST_NAME": latest_name,
            "MISSING_TABLE": missing_table,
            "POSTGRES_MIGRATIONS_DIR": str(
                _make_migrations_dir(tmp_path, migration_versions or [])
            ),
        }
    )
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        ["sh", str(VERIFY), *(extra_args or [])],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )


def test_lenient_mode_passes_when_repo_has_newer_migrations(tmp_path: Path) -> None:
    """迁移前必能备份：账本 1..5 连续，仓库已到 0007，默认模式仍通过。"""
    result = _run_verify(tmp_path, migration_versions=[1, 2, 3, 4, 5, 6, 7])
    assert result.returncode == 0, result.stderr
    assert "ledger_max=0005" in result.stdout


def test_strict_mode_fails_when_repo_has_newer_migrations(tmp_path: Path) -> None:
    result = _run_verify(
        tmp_path,
        migration_versions=[1, 2, 3, 4, 5, 6, 7],
        extra_args=["--strict"],
    )
    assert result.returncode == 1
    assert "does not span exactly versions 1 through 7" in result.stderr


def test_strict_mode_passes_at_repo_latest(tmp_path: Path) -> None:
    result = _run_verify(
        tmp_path,
        migration_versions=[1, 2, 3, 4, 5],
        extra_args=["--strict"],
    )
    assert result.returncode == 0, result.stderr
    assert "strict" in result.stdout


def test_strict_mode_via_env(tmp_path: Path) -> None:
    result = _run_verify(
        tmp_path,
        migration_versions=[1, 2, 3, 4, 5, 6],
        extra_env={"POSTGRES_VERIFY_STRICT": "1"},
    )
    assert result.returncode == 1
    assert "1 through 6" in result.stderr


def test_strict_mode_rejects_filename_mismatch(tmp_path: Path) -> None:
    result = _run_verify(
        tmp_path,
        migration_versions=[1, 2, 3, 4, 5],
        latest_name="0005_renamed.sql",
        extra_args=["--strict"],
    )
    assert result.returncode == 1
    assert "latest migration does not match" in result.stderr


def test_ledger_gap_fails_in_lenient_mode(tmp_path: Path) -> None:
    result = _run_verify(tmp_path, ledger_state="1|5|4")
    assert result.returncode == 1
    assert "not contiguous" in result.stderr


def test_ledger_series_gap_fails_in_lenient_mode(tmp_path: Path) -> None:
    result = _run_verify(tmp_path, ledger_state="1|5|5", contiguous="0")
    assert result.returncode == 1
    assert "version gap" in result.stderr


def test_empty_ledger_fails(tmp_path: Path) -> None:
    result = _run_verify(tmp_path, ledger_state="0|0|0")
    assert result.returncode == 1
    assert "does not start at version 1" in result.stderr


def test_missing_required_table_fails(tmp_path: Path) -> None:
    result = _run_verify(tmp_path, missing_table="documents")
    assert result.returncode == 1
    assert "public.documents is missing" in result.stderr


def test_missing_ledger_table_fails(tmp_path: Path) -> None:
    result = _run_verify(tmp_path, missing_table="app_schema_migrations")
    assert result.returncode == 1
    assert "app_schema_migrations is missing" in result.stderr


def test_unknown_argument_fails_with_usage(tmp_path: Path) -> None:
    result = _run_verify(tmp_path, extra_args=["--bogus"])
    assert result.returncode == 2
    assert "Usage:" in result.stderr
