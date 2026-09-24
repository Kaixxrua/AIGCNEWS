"""Tier-A 运维自愈脚本（scripts/ops_remediation.py）契约测试。

核心断言：
  - 白名单：应用层容器放行、数据层/未知容器拒绝；storage/ 树外或 symlink
    逃逸路径拒绝。
  - dry-run 零副作用：不带 --apply 时既不 docker restart、也不改任何权限。
  - --apply 才执行：带 --apply 时才 shell 出 docker / 才动文件属性。
  - 退出码契约：允许=0、拒绝=2、apply 失败=1。

不触碰真实 docker：执行层全部 mock。文件权限用 tmp 下真实临时树验证。
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts import ops_remediation


# --------------------------------------------------------------------------- #
# restart-container 白名单
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "name",
    ["aigc-backend", "aigc-frontend", "aigc-mcp-go"],
)
def test_restartable_containers_allowed(name: str) -> None:
    allowed, _ = ops_remediation.classify_container(name)
    assert allowed is True


@pytest.mark.parametrize(
    "name",
    [
        "docker-project-catalog-postgres-1",
        "redis-aigc",
        "milvus-standalone",
        "neo4j",
        "buildx_buildkit_goprobe0",
    ],
)
def test_protected_data_tier_denied(name: str) -> None:
    allowed, reason = ops_remediation.classify_container(name)
    assert allowed is False
    assert "受保护" in reason


@pytest.mark.parametrize("name", ["", "unknown-service", "aigc-backend-2"])
def test_unknown_containers_denied(name: str) -> None:
    allowed, _ = ops_remediation.classify_container(name)
    assert allowed is False


def test_restart_dry_run_does_not_shell_out() -> None:
    with patch.object(ops_remediation.subprocess, "run") as mock_run:
        result = ops_remediation.handle_restart("aigc-backend", apply=False)
    mock_run.assert_not_called()
    assert result.allowed is True
    assert result.applied is False
    assert result.plan == ["docker restart aigc-backend"]


def test_restart_denied_target_never_shells_out() -> None:
    with patch.object(ops_remediation.subprocess, "run") as mock_run:
        result = ops_remediation.handle_restart("redis-aigc", apply=True)
    mock_run.assert_not_called()
    assert result.allowed is False
    assert result.applied is False


def test_restart_apply_invokes_docker() -> None:
    fake = MagicMock(returncode=0, stdout="aigc-backend\n", stderr="")
    with patch.object(ops_remediation.subprocess, "run", return_value=fake) as mock_run:
        result = ops_remediation.handle_restart("aigc-backend", apply=True)
    mock_run.assert_called_once()
    argv = mock_run.call_args.args[0]
    assert argv == ["docker", "restart", "aigc-backend"]
    assert result.applied is True


# --------------------------------------------------------------------------- #
# fix-storage-perms 路径白名单
# --------------------------------------------------------------------------- #
def test_path_outside_storage_denied(tmp_path: Path) -> None:
    outside = tmp_path / "etc-passwd"
    outside.write_text("x", encoding="utf-8")
    _, allowed, reason = ops_remediation.validate_storage_path(str(outside))
    assert allowed is False
    assert "storage" in reason


def test_symlink_escape_denied(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """storage/ 内的 symlink 指向树外时，resolve 后必须判定为越界。"""
    storage = tmp_path / "storage"
    storage.mkdir()
    secret = tmp_path / "secret"
    secret.mkdir()
    link = storage / "escape"
    link.symlink_to(secret)
    monkeypatch.setattr(ops_remediation, "STORAGE_ROOT", storage)
    _, allowed, _ = ops_remediation.validate_storage_path(str(link))
    assert allowed is False


def test_path_inside_storage_allowed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    storage = tmp_path / "storage"
    papers = storage / "papers"
    papers.mkdir(parents=True)
    monkeypatch.setattr(ops_remediation, "STORAGE_ROOT", storage)
    resolved, allowed, _ = ops_remediation.validate_storage_path(str(papers))
    assert allowed is True
    assert resolved == papers.resolve()


def test_fix_perms_dry_run_changes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage = tmp_path / "storage"
    papers = storage / "papers"
    papers.mkdir(parents=True)
    victim = papers / "2609.24983.pdf"
    victim.write_text("pdf", encoding="utf-8")
    victim.chmod(0o600)
    monkeypatch.setattr(ops_remediation, "STORAGE_ROOT", storage)

    before = stat.S_IMODE(victim.stat().st_mode)
    result = ops_remediation.handle_fix_perms(
        str(papers), recursive=True, owner="", apply=False
    )
    after = stat.S_IMODE(victim.stat().st_mode)

    assert result.allowed is True
    assert result.applied is False
    assert before == after == 0o600  # dry-run 未改动
    assert result.plan  # 但给出了计划


def test_fix_perms_apply_normalizes_modes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage = tmp_path / "storage"
    papers = storage / "papers"
    papers.mkdir(parents=True)
    victim = papers / "2609.24983.pdf"
    victim.write_text("pdf", encoding="utf-8")
    victim.chmod(0o600)
    monkeypatch.setattr(ops_remediation, "STORAGE_ROOT", storage)

    result = ops_remediation.handle_fix_perms(
        str(papers), recursive=True, owner="", apply=True
    )

    assert result.applied is True
    assert stat.S_IMODE(victim.stat().st_mode) == ops_remediation.FILE_MODE
    assert stat.S_IMODE(papers.stat().st_mode) == ops_remediation.DIR_MODE


# --------------------------------------------------------------------------- #
# CLI 退出码 + 审计
# --------------------------------------------------------------------------- #
def test_cli_denied_exit_code_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    audit = tmp_path / "audit.jsonl"
    code = ops_remediation.main(
        ["--audit-log", str(audit), "restart-container", "redis-aigc"]
    )
    assert code == 2
    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["allowed"] is False
    assert payload["action"] == "restart-container"


def test_cli_dry_run_exit_code_0_and_audits(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    audit = tmp_path / "audit.jsonl"
    with patch.object(ops_remediation.subprocess, "run") as mock_run:
        code = ops_remediation.main(
            ["--audit-log", str(audit), "restart-container", "aigc-backend"]
        )
    mock_run.assert_not_called()
    assert code == 0
    capsys.readouterr()
    assert audit.exists()
    line = json.loads(audit.read_text(encoding="utf-8").strip())
    assert line["target"] == "aigc-backend"
    assert "timestamp" in line


def test_cli_apply_failure_exit_code_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    audit = tmp_path / "audit.jsonl"
    fake = MagicMock(returncode=1, stdout="", stderr="No such container")
    with patch.object(ops_remediation.subprocess, "run", return_value=fake):
        code = ops_remediation.main(
            ["--audit-log", str(audit), "--apply", "restart-container", "aigc-backend"]
        )
    assert code == 1
    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["allowed"] is True
    assert payload["applied"] is False


def test_audit_failure_never_raises(tmp_path: Path) -> None:
    """审计写入失败（目录不可创建）不得抛出、不得改变主动作退出码。"""
    result = ops_remediation.RemediationResult(
        action="restart-container",
        target="aigc-backend",
        allowed=True,
        applied=False,
        reason="test",
    )
    unwritable = tmp_path / "file-as-dir"
    unwritable.write_text("x", encoding="utf-8")
    # 把审计路径的父级指到一个"文件"下，使 mkdir 失败。
    bogus = unwritable / "nested" / "audit.jsonl"
    ops_remediation._append_audit(bogus, result)  # 不应抛出
