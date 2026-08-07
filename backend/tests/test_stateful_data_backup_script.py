"""非 PG 有状态数据快照脚本(scripts/backup_stateful_data_scheduled.sh)契约测试。

用真实 tar 在 tmp_path 里构造微型源目录,验证快照内容、缺失源跳过、保留
策略(tar.gz 与 .sha256 成对修剪)、失败告警钩子等,不触碰宿主机真实数据。
"""

from __future__ import annotations

import os
import stat
import subprocess
import tarfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "backup_stateful_data_scheduled.sh"

STUB_ALERT = (
    "import os, sys\n"
    "open(os.environ['ALERT_LOG'], 'a', encoding='utf-8').write(' '.join(sys.argv[1:]) + '\\n')\n"
    "sys.exit(int(os.environ.get('ALERT_STUB_RC', '0')))\n"
)


def _seed_sources(base: Path) -> None:
    (base / "storage" / "wechat").mkdir(parents=True)
    (base / "storage" / "wechat" / "article.html").write_text("<html>cached</html>", encoding="utf-8")
    (base / "storage" / "metrics").mkdir(parents=True)
    (base / "storage" / "metrics" / "mcp_tool_calls.json").write_text("{}", encoding="utf-8")


def _write_alert_stub(directory: Path) -> Path:
    stub = directory / "stub_alert.py"
    stub.write_text(STUB_ALERT)
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR)
    return stub


def _run(
    base: Path,
    backup_dir: Path,
    *,
    retention: str = "2",
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(
        {
            "AIGCNEWS_STATEFUL_BASE": str(base),
            "AIGCNEWS_STATEFUL_BACKUP_DIR": str(backup_dir),
            "AIGCNEWS_STATEFUL_RETENTION": retention,
        }
    )
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        ["/bin/sh", str(SCRIPT)], capture_output=True, text=True, env=env, timeout=60
    )


def _alert_env(tmp_path: Path) -> dict[str, str]:
    stub = _write_alert_stub(tmp_path)
    return {
        "AIGCNEWS_OPS_ALERT_SCRIPT": str(stub),
        "ALERT_LOG": str(tmp_path / "alert.log"),
    }


def _alert_calls(tmp_path: Path) -> str:
    log = tmp_path / "alert.log"
    return log.read_text(encoding="utf-8") if log.exists() else ""


def _seed_snapshot(directory: Path, stamp: str) -> None:
    (directory / f"aigcnews-stateful-{stamp}.tar.gz").write_bytes(b"old")
    (directory / f"aigcnews-stateful-{stamp}.tar.gz.sha256").write_text("deadbeef")


def _snapshot_stamps(directory: Path) -> list[str]:
    return sorted(path.name for path in directory.glob("aigcnews-stateful-*.tar.gz"))


def test_snapshot_archives_existing_sources_and_writes_sha256(tmp_path: Path) -> None:
    base = tmp_path / "repo"
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    _seed_sources(base)

    result = _run(base, backup_dir)

    assert result.returncode == 0, result.stderr
    snapshots = _snapshot_stamps(backup_dir)
    assert len(snapshots) == 1
    archive = backup_dir / snapshots[0]
    with tarfile.open(archive) as tar:
        names = tar.getnames()
    assert any(name.endswith("storage/wechat/article.html") for name in names)
    assert any(name.endswith("storage/metrics/mcp_tool_calls.json") for name in names)
    assert (Path(str(archive) + ".sha256")).exists()
    # 缺失的 _chat_uploads 被跳过但快照仍然成功
    assert "skipped" in result.stderr


def test_snapshot_prunes_beyond_retention(tmp_path: Path) -> None:
    base = tmp_path / "repo"
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    _seed_sources(base)
    _seed_snapshot(backup_dir, "20200101-000000")
    _seed_snapshot(backup_dir, "20200102-000000")

    result = _run(base, backup_dir, retention="2")

    assert result.returncode == 0, result.stderr
    names = _snapshot_stamps(backup_dir)
    assert "aigcnews-stateful-20200101-000000.tar.gz" not in names
    assert "aigcnews-stateful-20200102-000000.tar.gz" in names
    assert len(names) == 2
    assert not (backup_dir / "aigcnews-stateful-20200101-000000.tar.gz.sha256").exists()


def test_fails_when_no_sources_present(tmp_path: Path) -> None:
    base = tmp_path / "repo"
    backup_dir = tmp_path / "backups"
    base.mkdir()
    backup_dir.mkdir()

    result = _run(base, backup_dir, extra_env=_alert_env(tmp_path))

    assert result.returncode == 1
    assert "no snapshot sources" in result.stderr
    calls = _alert_calls(tmp_path)
    assert "--failed-unit aigcnews-stateful-backup" in calls


def test_missing_backup_dir_fails_and_alerts(tmp_path: Path) -> None:
    base = tmp_path / "repo"
    _seed_sources(base)

    result = _run(base, tmp_path / "missing", extra_env=_alert_env(tmp_path))

    assert result.returncode == 1
    assert "backup directory does not exist" in result.stderr
    assert "aigcnews-stateful-backup" in _alert_calls(tmp_path)


def test_alert_disabled_skips_invocation(tmp_path: Path) -> None:
    base = tmp_path / "repo"
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    _seed_sources(base)
    extra = {**_alert_env(tmp_path), "AIGCNEWS_OPS_ALERT_DISABLED": "1", "AIGCNEWS_STATEFUL_RETENTION": "abc"}

    result = _run(base, backup_dir, extra_env=extra)

    assert result.returncode == 1
    assert _alert_calls(tmp_path) == ""


def test_alert_failure_does_not_mask_snapshot_result(tmp_path: Path) -> None:
    base = tmp_path / "repo"
    base.mkdir()
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    extra = {**_alert_env(tmp_path), "ALERT_STUB_RC": "1"}

    result = _run(base, backup_dir, extra_env=extra)

    # 无任何源导致失败;告警桩失败不得遮蔽该退出码
    assert result.returncode == 1
    assert "no snapshot sources" in result.stderr
