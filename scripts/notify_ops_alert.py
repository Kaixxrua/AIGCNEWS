#!/usr/bin/env python3
"""AIGCNEWS 运维失败告警邮件脚本。

用途：定时备份等运维任务失败时发送邮件告警。仅依赖标准库，可由 systemd
oneshot 单元或 shell 包装脚本直接调用（失败时不影响原任务退出码）。

配置来源（优先级从高到低）：
1. 进程环境变量；
2. .env 风格文件（--env-file，默认 <repo>/.env，可用
   AIGCNEWS_OPS_ALERT_ENV_FILE 覆盖默认值）。

需要的键：SMTP_HOST、SMTP_PORT、SMTP_USERNAME、SMTP_PASSWORD、
SMTP_FROM_EMAIL、SMTP_FROM_NAME、SMTP_USE_TLS（与项目 .env 同名同义）。
收件人：AIGCNEWS_OPS_ALERT_TO 或 --to，缺省回退 SMTP_FROM_EMAIL（自发）。
"""

from __future__ import annotations

import argparse
import os
import smtplib
import socket
import ssl
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENV_FILE = REPO_ROOT / ".env"
SMTP_TIMEOUT_SECONDS = 20


@dataclass(frozen=True)
class AlertConfig:
    host: str
    port: int
    username: str
    password: str
    from_email: str
    from_name: str
    use_tls: bool
    recipient: str


def load_env_file(path: Path) -> dict[str, str]:
    """解析 KEY=VALUE 行，忽略注释与空行，剥离成对引号；文件缺失返回空。"""
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return values
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, raw = stripped.partition("=")
        key = key.strip()
        value = raw.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        if key:
            values[key] = value
    return values


def _truthy(value: str) -> bool:
    return value.strip().lower() in ("1", "true", "yes", "on")


def resolve_config(env_file: Path, environ: dict[str, str], recipient_override: str = "") -> AlertConfig:
    file_values = load_env_file(env_file)

    def get(key: str) -> str:
        return environ.get(key) or file_values.get(key) or ""

    use_tls = _truthy(get("SMTP_USE_TLS"))
    port_raw = get("SMTP_PORT")
    port = int(port_raw) if port_raw.isdigit() else (587 if use_tls else 465)
    recipient = recipient_override or get("AIGCNEWS_OPS_ALERT_TO") or get("SMTP_FROM_EMAIL")
    return AlertConfig(
        host=get("SMTP_HOST"),
        port=port,
        username=get("SMTP_USERNAME"),
        password=get("SMTP_PASSWORD"),
        from_email=get("SMTP_FROM_EMAIL"),
        from_name=get("SMTP_FROM_NAME"),
        use_tls=use_tls,
        recipient=recipient,
    )


def journal_tail(unit: str, lines: int = 15) -> str:
    """尽力而为地取失败单元最近日志；任何失败都返回空串而不是抛出。"""
    if not unit:
        return ""
    try:
        result = subprocess.run(
            ["journalctl", "-u", unit, "-n", str(lines), "--no-pager", "-q"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return result.stdout.strip()


def build_message(config: AlertConfig, failed_unit: str, detail: str, logs: str) -> EmailMessage:
    host_name = socket.gethostname()
    timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
    message = EmailMessage()
    message["Subject"] = f"[AIGCNEWS 告警] {host_name}: {failed_unit} 失败"
    message["From"] = f"{config.from_name} <{config.from_email}>" if config.from_name else config.from_email
    message["To"] = config.recipient
    body_parts = [
        f"时间: {timestamp}",
        f"主机: {host_name}",
        f"失败单元: {failed_unit}",
    ]
    if detail:
        body_parts.append(f"详情: {detail}")
    if logs:
        body_parts.append(f"\n最近日志:\n{logs}")
    else:
        body_parts.append("\n最近日志: （不可用，请手动执行 journalctl 查看）")
    message.set_content("\n".join(body_parts) + "\n")
    return message


def send_alert(config: AlertConfig, message: EmailMessage) -> None:
    context = ssl.create_default_context()
    if config.use_tls:
        with smtplib.SMTP(config.host, config.port, timeout=SMTP_TIMEOUT_SECONDS) as smtp:
            smtp.ehlo()
            smtp.starttls(context=context)
            smtp.ehlo()
            if config.username:
                smtp.login(config.username, config.password)
            smtp.send_message(message)
    elif config.port == 465:
        with smtplib.SMTP_SSL(config.host, config.port, timeout=SMTP_TIMEOUT_SECONDS, context=context) as smtp:
            if config.username:
                smtp.login(config.username, config.password)
            smtp.send_message(message)
    else:
        with smtplib.SMTP(config.host, config.port, timeout=SMTP_TIMEOUT_SECONDS) as smtp:
            if config.username:
                smtp.login(config.username, config.password)
            smtp.send_message(message)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="发送 AIGCNEWS 运维失败告警邮件。")
    parser.add_argument("--failed-unit", required=True, help="失败的任务/单元名称，写入主题与正文")
    parser.add_argument("--detail", default="", help="附加详情（如失败步骤）")
    parser.add_argument("--to", default="", help="收件人，缺省回退 AIGCNEWS_OPS_ALERT_TO / SMTP_FROM_EMAIL")
    parser.add_argument(
        "--env-file",
        default=os.environ.get("AIGCNEWS_OPS_ALERT_ENV_FILE", str(DEFAULT_ENV_FILE)),
        help="SMTP 配置 env 文件（默认 <repo>/.env）",
    )
    parser.add_argument("--no-journal", action="store_true", help="不附带 journalctl 日志尾巴")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = resolve_config(Path(args.env_file), dict(os.environ), recipient_override=args.to)
    if not config.host or not config.from_email:
        print("ops alert skipped: SMTP_HOST/SMTP_FROM_EMAIL 未配置", file=sys.stderr)
        return 2
    if not config.recipient:
        print("ops alert skipped: 无收件人（--to / AIGCNEWS_OPS_ALERT_TO / SMTP_FROM_EMAIL 均为空）", file=sys.stderr)
        return 2
    logs = "" if args.no_journal else journal_tail(args.failed_unit)
    message = build_message(config, args.failed_unit, args.detail, logs)
    try:
        send_alert(config, message)
    except (OSError, smtplib.SMTPException) as exc:
        print(f"ops alert send failed: {exc}", file=sys.stderr)
        return 1
    print(f"ops alert sent to {config.recipient} for {args.failed_unit}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
