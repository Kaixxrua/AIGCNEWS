"""运维告警脚本(scripts/notify_ops_alert.py)契约测试。

不触碰真实 SMTP:发送层全部 mock;配置解析与降级逻辑用临时 env 文件。
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts import notify_ops_alert


@pytest.fixture(autouse=True)
def _clean_ambient_alert_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """清除进程级 SMTP_*/AIGCNEWS_OPS_ALERT_* 环境变量。

    pymilvus 在 import 时会 load_dotenv() 把项目 .env 注入 os.environ；
    本地全量跑过 pymilvus 相关用例后，本模块的 main() 测试会读到真实
    SMTP 配置而偏离预期，因此统一隔离。
    """
    for key in list(os.environ):
        if key.startswith(("SMTP_", "AIGCNEWS_OPS_ALERT_")):
            monkeypatch.delenv(key, raising=False)


def _write_env(tmp_path: Path, body: str) -> Path:
    env_file = tmp_path / "smtp.env"
    env_file.write_text(body, encoding="utf-8")
    return env_file


def _base_config(**overrides: str) -> notify_ops_alert.AlertConfig:
    values = {
        "host": "smtp.example.com",
        "port": 465,
        "username": "bot@example.com",
        "password": "secret",
        "from_email": "bot@example.com",
        "from_name": "AIGCNEWS Bot",
        "use_tls": False,
        "recipient": "ops@example.com",
    }
    return notify_ops_alert.AlertConfig(**{**values, **overrides})


class TestLoadEnvFile:
    def test_parses_key_value_and_strips_quotes(self, tmp_path: Path) -> None:
        env_file = _write_env(
            tmp_path,
            "# comment\n\nSMTP_HOST='smtp.example.com'\nSMTP_FROM_EMAIL=\"bot@example.com\"\nEMPTY=\n",
        )

        values = notify_ops_alert.load_env_file(env_file)

        assert values == {
            "SMTP_HOST": "smtp.example.com",
            "SMTP_FROM_EMAIL": "bot@example.com",
            "EMPTY": "",
        }

    def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        assert notify_ops_alert.load_env_file(tmp_path / "nope.env") == {}


class TestResolveConfig:
    def test_environ_takes_precedence_over_file(self, tmp_path: Path) -> None:
        env_file = _write_env(tmp_path, "SMTP_HOST=file-host\nSMTP_PORT=465\n")

        config = notify_ops_alert.resolve_config(env_file, {"SMTP_HOST": "env-host"})

        assert config.host == "env-host"
        assert config.port == 465

    def test_defaults_tls_port_587_and_ssl_port_465(self, tmp_path: Path) -> None:
        env_file = _write_env(tmp_path, "SMTP_USE_TLS=true\n")

        tls_config = notify_ops_alert.resolve_config(env_file, {})
        plain_config = notify_ops_alert.resolve_config(tmp_path / "nope.env", {})

        assert tls_config.use_tls is True
        assert tls_config.port == 587
        assert plain_config.use_tls is False
        assert plain_config.port == 465

    def test_recipient_falls_back_to_from_email(self, tmp_path: Path) -> None:
        env_file = _write_env(tmp_path, "SMTP_FROM_EMAIL=bot@example.com\n")

        config = notify_ops_alert.resolve_config(env_file, {})

        assert config.recipient == "bot@example.com"


class TestBuildMessage:
    def test_subject_and_body_carry_unit_host_detail(self) -> None:
        message = notify_ops_alert.build_message(
            _base_config(), "aigcnews-postgres-backup", "pg_dump rc=1", "log line"
        )

        assert "aigcnews-postgres-backup" in message["Subject"]
        assert message["From"] == "AIGCNEWS Bot <bot@example.com>"
        assert message["To"] == "ops@example.com"
        body = message.get_content()
        assert "pg_dump rc=1" in body
        assert "log line" in body

    def test_from_header_without_name(self) -> None:
        message = notify_ops_alert.build_message(_base_config(from_name=""), "unit-x", "", "")

        assert message["From"] == "bot@example.com"


class TestSendAlert:
    def test_tls_path_starttls_then_login_then_send(self) -> None:
        config = _base_config(port=587, use_tls=True)
        smtp = MagicMock()
        with patch.object(notify_ops_alert.smtplib, "SMTP", return_value=smtp) as smtp_cls:
            smtp.__enter__.return_value = smtp
            notify_ops_alert.send_alert(config, MagicMock())

        smtp_cls.assert_called_once_with("smtp.example.com", 587, timeout=20)
        smtp.starttls.assert_called_once()
        smtp.login.assert_called_once_with("bot@example.com", "secret")
        smtp.send_message.assert_called_once()

    def test_ssl_path_used_for_port_465(self) -> None:
        config = _base_config(port=465, use_tls=False)
        smtp = MagicMock()
        smtp.__enter__.return_value = smtp
        with patch.object(notify_ops_alert.smtplib, "SMTP_SSL", return_value=smtp) as smtp_cls:
            notify_ops_alert.send_alert(config, MagicMock())

        assert smtp_cls.call_args.args[:2] == ("smtp.example.com", 465)
        smtp.send_message.assert_called_once()

    def test_login_skipped_without_username(self) -> None:
        config = _base_config(username="", password="")
        smtp = MagicMock()
        smtp.__enter__.return_value = smtp
        with patch.object(notify_ops_alert.smtplib, "SMTP_SSL", return_value=smtp):
            notify_ops_alert.send_alert(config, MagicMock())

        smtp.login.assert_not_called()


class TestJournalTail:
    def test_returns_empty_on_oserror(self) -> None:
        with patch.object(notify_ops_alert.subprocess, "run", side_effect=FileNotFoundError):
            assert notify_ops_alert.journal_tail("any.service") == ""

    def test_returns_empty_for_blank_unit(self) -> None:
        assert notify_ops_alert.journal_tail("") == ""


class TestMain:
    def test_missing_smtp_host_returns_2(self, tmp_path: Path) -> None:
        code = notify_ops_alert.main(
            ["--failed-unit", "x", "--env-file", str(tmp_path / "nope.env"), "--no-journal"]
        )
        assert code == 2

    def test_send_failure_returns_1(self, tmp_path: Path) -> None:
        env_file = _write_env(tmp_path, "SMTP_HOST=smtp.example.com\nSMTP_FROM_EMAIL=bot@example.com\n")
        with patch.object(
            notify_ops_alert.smtplib, "SMTP_SSL", side_effect=OSError("connection refused")
        ):
            code = notify_ops_alert.main(["--failed-unit", "x", "--env-file", str(env_file), "--no-journal"])
        assert code == 1

    def test_happy_path_returns_0(self, tmp_path: Path) -> None:
        env_file = _write_env(tmp_path, "SMTP_HOST=smtp.example.com\nSMTP_FROM_EMAIL=bot@example.com\n")
        smtp = MagicMock()
        smtp.__enter__.return_value = smtp
        with patch.object(notify_ops_alert.smtplib, "SMTP_SSL", return_value=smtp):
            code = notify_ops_alert.main(["--failed-unit", "x", "--env-file", str(env_file), "--no-journal"])
        assert code == 0
        smtp.send_message.assert_called_once()


class TestJournalIntegration:
    """journalctl 在本机存在时对不存在单元也不应抛出。"""

    def test_bogus_unit_does_not_raise(self) -> None:
        if not Path("/usr/bin/journalctl").exists():
            pytest.skip("journalctl unavailable")
        result = subprocess.run(
            ["journalctl", "-u", "aigcnews-no-such-unit.service", "-n", "1", "--no-pager", "-q"],
            capture_output=True,
            timeout=10,
            check=False,
        )
        assert result.returncode in (0, 1)
