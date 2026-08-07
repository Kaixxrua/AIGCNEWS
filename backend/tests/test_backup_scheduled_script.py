"""定时备份包装脚本（scripts/backup_postgres_application_scheduled.sh）契约测试。

通过 AIGCNEWS_BACKUP_SCRIPT 注入桩备份脚本，验证时间戳命名、保留策略
（dump 与 .sha256 成对修剪）、失败传播与参数校验，不触碰真实数据库。
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WRAPPER = REPO_ROOT / "scripts" / "backup_postgres_application_scheduled.sh"

STUB_OK = "#!/bin/sh\ntouch -- \"$1\" \"$1.sha256\"\n"
STUB_FAIL = "#!/bin/sh\necho boom >&2\nexit 1\n"

# 告警桩：python 脚本（包装脚本经 python3 调用），把参数追加到 ALERT_LOG，退出码受 ALERT_STUB_RC 控制
STUB_ALERT = (
    "import os, sys\n"
    "open(os.environ['ALERT_LOG'], 'a', encoding='utf-8').write(' '.join(sys.argv[1:]) + '\\n')\n"
    "sys.exit(int(os.environ.get('ALERT_STUB_RC', '0')))\n"
)


def _write_stub(directory: Path, body: str, name: str = "stub_backup.sh") -> Path:
    stub = directory / name
    stub.write_text(body)
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return stub


def _seed_backup(directory: Path, stamp: str) -> None:
    (directory / f"aigcnews-{stamp}.dump").write_bytes(b"old")
    (directory / f"aigcnews-{stamp}.dump.sha256").write_text("deadbeef")


def _run_wrapper(
    tmp_path: Path,
    stub: Path,
    *,
    retention: str = "2",
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(
        {
            "AIGCNEWS_BACKUP_SCRIPT": str(stub),
            "AIGCNEWS_BACKUP_DIR": str(tmp_path),
            "AIGCNEWS_BACKUP_RETENTION": retention,
            # 指向不存在的环境文件，隔离宿主机真实凭据
            "BACKUP_ENV_FILE": str(tmp_path / "no-such.env"),
        }
    )
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        ["/bin/sh", str(WRAPPER)],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )


def _alert_env(tmp_path: Path) -> dict[str, str]:
    """告警桩 + 记录文件的环境组合（包装脚本经 python3 调用桩）。"""
    stub = _write_stub(tmp_path, STUB_ALERT, name="stub_alert.py")
    return {
        "AIGCNEWS_OPS_ALERT_SCRIPT": str(stub),
        "ALERT_LOG": str(tmp_path / "alert.log"),
    }


def _alert_calls(tmp_path: Path) -> str:
    log = tmp_path / "alert.log"
    return log.read_text(encoding="utf-8") if log.exists() else ""


def _dump_stamps(directory: Path) -> list[str]:
    return sorted(path.name for path in directory.glob("aigcnews-*.dump"))


def test_scheduled_backup_creates_timestamped_dump_and_prunes_beyond_retention(tmp_path: Path) -> None:
    stub = _write_stub(tmp_path, STUB_OK)
    _seed_backup(tmp_path, "20200101-000000")
    _seed_backup(tmp_path, "20200102-000000")

    result = _run_wrapper(tmp_path, stub)

    assert result.returncode == 0, result.stderr
    stamps = _dump_stamps(tmp_path)
    # 保留最新 2 份：新生的时间戳 + 20200102；最旧的 20200101 连同 sha256 被修剪
    assert "aigcnews-20200101-000000.dump" not in stamps
    assert "aigcnews-20200102-000000.dump" in stamps
    assert len(stamps) == 2
    assert not (tmp_path / "aigcnews-20200101-000000.dump.sha256").exists()
    assert (tmp_path / "aigcnews-20200102-000000.dump.sha256").exists()
    assert not (tmp_path / "aigcnews-20200103-000000.dump").exists()


def test_scheduled_backup_propagates_backup_failure_without_pruning(tmp_path: Path) -> None:
    stub = _write_stub(tmp_path, STUB_FAIL)
    _seed_backup(tmp_path, "20200101-000000")

    result = _run_wrapper(tmp_path, stub)

    assert result.returncode == 1
    assert "boom" in result.stderr
    # 失败时不得误删既有备份
    assert (tmp_path / "aigcnews-20200101-000000.dump").exists()
    assert (tmp_path / "aigcnews-20200101-000000.dump.sha256").exists()


def test_scheduled_backup_rejects_non_numeric_retention(tmp_path: Path) -> None:
    stub = _write_stub(tmp_path, STUB_OK)

    result = _run_wrapper(tmp_path, stub, retention="abc")

    assert result.returncode == 1
    assert "AIGCNEWS_BACKUP_RETENTION must be a positive integer" in result.stderr


def test_scheduled_backup_requires_existing_backup_dir(tmp_path: Path) -> None:
    stub = _write_stub(tmp_path, STUB_OK)
    missing = tmp_path / "missing-dir"

    env = os.environ.copy()
    env.update(
        {
            "AIGCNEWS_BACKUP_SCRIPT": str(stub),
            "AIGCNEWS_BACKUP_DIR": str(missing),
            "BACKUP_ENV_FILE": str(tmp_path / "no-such.env"),
        }
    )
    result = subprocess.run(
        ["/bin/sh", str(WRAPPER)], capture_output=True, text=True, env=env, timeout=30
    )

    assert result.returncode == 1
    assert "backup directory does not exist" in result.stderr


def test_backup_failure_invokes_alert_with_unit_and_detail(tmp_path: Path) -> None:
    stub = _write_stub(tmp_path, STUB_FAIL)

    result = _run_wrapper(tmp_path, stub, extra_env=_alert_env(tmp_path))

    assert result.returncode == 1
    calls = _alert_calls(tmp_path)
    assert "--failed-unit aigcnews-postgres-backup" in calls
    assert "backup script failed" in calls


def test_successful_backup_does_not_alert(tmp_path: Path) -> None:
    stub = _write_stub(tmp_path, STUB_OK)

    result = _run_wrapper(tmp_path, stub, extra_env=_alert_env(tmp_path))

    assert result.returncode == 0, result.stderr
    assert _alert_calls(tmp_path) == ""


def test_alert_failure_does_not_mask_backup_result(tmp_path: Path) -> None:
    stub = _write_stub(tmp_path, STUB_FAIL)
    extra = {**_alert_env(tmp_path), "ALERT_STUB_RC": "1"}

    result = _run_wrapper(tmp_path, stub, extra_env=extra)

    # 告警桩自身失败不得改变备份失败的真实退出码与 stderr
    assert result.returncode == 1
    assert "boom" in result.stderr


def test_alert_disabled_skips_invocation(tmp_path: Path) -> None:
    stub = _write_stub(tmp_path, STUB_FAIL)
    extra = {**_alert_env(tmp_path), "AIGCNEWS_OPS_ALERT_DISABLED": "1"}

    result = _run_wrapper(tmp_path, stub, extra_env=extra)

    assert result.returncode == 1
    assert _alert_calls(tmp_path) == ""


def test_validation_failure_alerts(tmp_path: Path) -> None:
    stub = _write_stub(tmp_path, STUB_OK)

    result = _run_wrapper(tmp_path, stub, retention="abc", extra_env=_alert_env(tmp_path))

    assert result.returncode == 1
    calls = _alert_calls(tmp_path)
    assert "--failed-unit aigcnews-postgres-backup" in calls
    assert "AIGCNEWS_BACKUP_RETENTION" in calls
