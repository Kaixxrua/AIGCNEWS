#!/usr/bin/env python3
"""AIGCNEWS Tier-A 运维自愈动作（受限、幂等、默认 dry-run）。

给"AI 运维"暴露的第一批"手"：把只会发邮件告警的观测型运维，升级为可以
对**确定性、低爆炸半径、可回滚**的故障自行执行修复。仅依赖标准库，可由
运维 agent、systemd oneshot 或 shell 直接调用。

安全信封（与 CLAUDE.md 的 Red 变更红线对齐）：
  1. 默认 dry-run：只打印将要执行的结构化计划并退出，**不产生副作用**；
     必须显式传 ``--apply`` 才执行。
  2. 硬白名单：``restart-container`` 只允许应用层容器（显式拒绝数据层
     postgres/redis/milvus/neo4j 等）；``fix-storage-perms`` 只允许作用于
     仓库 ``storage/`` 目录树内、经 resolve 后仍在其中的路径（防 symlink 逃逸）。
  3. 幂等：重启天然幂等；chown/chmod 到目标属主/模式重复执行结果一致。
  4. 审计留痕：每次调用（含 dry-run）尽力追加一行 JSONL 到审计日志；审计
     失败绝不阻断或改变主动作的结果。

输出：单个 JSON 对象到 stdout（供 agent 解析）。退出码 0 表示动作被允许
（dry-run 计划成功或 apply 成功执行）；2 表示目标被白名单拒绝；1 表示 apply
执行失败。
"""

from __future__ import annotations

import argparse
import grp
import json
import os
import pwd
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
STORAGE_ROOT = REPO_ROOT / "storage"
DEFAULT_AUDIT_LOG = REPO_ROOT / "storage" / "metrics" / "ops_remediation_audit.jsonl"
DOCKER_TIMEOUT_SECONDS = 90

# 允许重启的应用层容器：无状态、重启可自愈、丢失重启期间请求可接受。
RESTARTABLE_CONTAINERS = frozenset(
    {
        "aigc-backend",
        "aigc-frontend",
        "aigc-mcp-go",
    }
)
# 显式保护的数据层/有状态容器：重启有数据或长连接风险，Tier-A 永不自动触碰。
# 命中这些前缀会给出更清晰的拒绝理由，而不是笼统的"不在白名单"。
PROTECTED_CONTAINER_PREFIXES = (
    "docker-project-catalog-postgres",
    "redis",
    "milvus",
    "neo4j",
    "buildx",
)

# fix-storage-perms 目标模式：目录 0o775 / 普通文件 0o664（组可写，配合容器
# 与宿主同组的常见部署）。
DIR_MODE = 0o775
FILE_MODE = 0o664


@dataclass
class RemediationResult:
    """一次自愈动作的结构化结果，序列化为 JSON 交给 agent。"""

    action: str
    target: str
    allowed: bool
    applied: bool
    reason: str
    plan: list[str] = field(default_factory=list)
    outcome: str = ""
    changed: int = 0

    def to_json(self) -> str:
        payload: dict[str, Any] = asdict(self)
        payload["timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        return json.dumps(payload, ensure_ascii=False)


def _append_audit(audit_log: Path, result: RemediationResult) -> None:
    """尽力追加审计行；任何失败只写 stderr，绝不影响主动作结果。"""
    try:
        audit_log.parent.mkdir(parents=True, exist_ok=True)
        with audit_log.open("a", encoding="utf-8") as handle:
            handle.write(result.to_json() + "\n")
    except OSError as exc:  # pragma: no cover - 审计降级路径
        print(f"ops remediation audit skipped: {exc}", file=sys.stderr)


# --------------------------------------------------------------------------- #
# restart-container
# --------------------------------------------------------------------------- #
def classify_container(name: str) -> tuple[bool, str]:
    """判定容器是否允许 Tier-A 重启。返回 (allowed, reason)。"""
    if not name:
        return False, "容器名为空"
    if name in RESTARTABLE_CONTAINERS:
        return True, "在应用层重启白名单内"
    for prefix in PROTECTED_CONTAINER_PREFIXES:
        if name.startswith(prefix):
            return False, f"数据层/有状态容器（前缀 {prefix!r}）受保护，Tier-A 禁止重启"
    return False, "不在应用层重启白名单内，拒绝"


def execute_restart(name: str) -> tuple[bool, str]:
    """执行 docker restart；返回 (success, outcome)。"""
    try:
        proc = subprocess.run(
            ["docker", "restart", name],
            capture_output=True,
            text=True,
            timeout=DOCKER_TIMEOUT_SECONDS,
            check=False,
        )
    except FileNotFoundError:
        return False, "docker 不可用（未安装或不在 PATH）"
    except subprocess.TimeoutExpired:
        return False, f"docker restart 超时（>{DOCKER_TIMEOUT_SECONDS}s）"
    if proc.returncode != 0:
        return False, (proc.stderr or proc.stdout or "").strip()[:300]
    return True, (proc.stdout or "").strip()[:200] or f"{name} restarted"


def handle_restart(name: str, apply: bool) -> RemediationResult:
    allowed, reason = classify_container(name)
    result = RemediationResult(
        action="restart-container",
        target=name,
        allowed=allowed,
        applied=False,
        reason=reason,
        plan=[f"docker restart {name}"] if allowed else [],
    )
    if not allowed or not apply:
        result.outcome = "dry-run（未执行）" if allowed else "拒绝（白名单外）"
        return result
    success, outcome = execute_restart(name)
    result.applied = success
    result.outcome = outcome
    return result


# --------------------------------------------------------------------------- #
# fix-storage-perms
# --------------------------------------------------------------------------- #
def validate_storage_path(raw: str) -> tuple[Path | None, bool, str]:
    """解析目标路径，要求 resolve 后仍在 storage/ 树内（防 symlink 逃逸）。"""
    if not raw:
        return None, False, "路径为空"
    try:
        resolved = Path(raw).resolve()
        storage_resolved = STORAGE_ROOT.resolve()
    except OSError as exc:
        return None, False, f"路径无法解析: {exc}"
    if resolved != storage_resolved and storage_resolved not in resolved.parents:
        return resolved, False, f"路径不在 {storage_resolved} 树内，拒绝"
    if not resolved.exists():
        return resolved, False, "路径不存在"
    return resolved, True, "在 storage/ 树内且存在"


def _resolve_owner(owner: str) -> tuple[int | None, int | None, str]:
    """把 ``uid[:gid]`` / ``user[:group]`` 解析成数值 (uid, gid)。空串表示不改属主。"""
    if not owner:
        return None, None, "不改属主"
    user_part, _, group_part = owner.partition(":")
    try:
        uid = int(user_part) if user_part.isdigit() else pwd.getpwnam(user_part).pw_uid
    except (KeyError, ValueError):
        raise ValueError(f"无法解析用户 {user_part!r}") from None
    gid: int | None = None
    if group_part:
        try:
            gid = int(group_part) if group_part.isdigit() else grp.getgrnam(group_part).gr_gid
        except (KeyError, ValueError):
            raise ValueError(f"无法解析用户组 {group_part!r}") from None
    return uid, gid, f"目标属主 {uid}:{gid if gid is not None else '(保持)'}"


def _iter_targets(root: Path, recursive: bool) -> list[Path]:
    if not recursive or root.is_file():
        return [root]
    targets = [root]
    for child in root.rglob("*"):
        targets.append(child)
    return targets


def execute_fix_perms(
    resolved: Path, recursive: bool, uid: int | None, gid: int | None
) -> tuple[bool, str, int]:
    """对目标应用 chmod（目录/文件分别到 DIR_MODE/FILE_MODE）并可选 chown。"""
    changed = 0
    try:
        for target in _iter_targets(resolved, recursive):
            desired_mode = DIR_MODE if target.is_dir() else FILE_MODE
            current_mode = target.stat().st_mode & 0o777
            if current_mode != desired_mode:
                target.chmod(desired_mode)
                changed += 1
            if uid is not None:
                os.chown(target, uid, gid if gid is not None else -1)
                changed += 1
    except OSError as exc:
        return False, f"chmod/chown 失败: {exc}", changed
    return True, f"已调整 {changed} 处属性", changed


def handle_fix_perms(
    raw_path: str, recursive: bool, owner: str, apply: bool
) -> RemediationResult:
    resolved, allowed, reason = validate_storage_path(raw_path)
    target_str = str(resolved) if resolved else raw_path
    result = RemediationResult(
        action="fix-storage-perms",
        target=target_str,
        allowed=allowed,
        applied=False,
        reason=reason,
    )
    if not allowed:
        result.outcome = "拒绝（storage/ 树外或不存在）"
        return result
    try:
        uid, gid, owner_desc = _resolve_owner(owner)
    except ValueError as exc:
        result.allowed = False
        result.reason = str(exc)
        result.outcome = "拒绝（属主无法解析）"
        return result
    scope = "递归" if recursive else "仅目标"
    result.plan = [
        f"chmod 目录→{oct(DIR_MODE)} 文件→{oct(FILE_MODE)}（{scope}）",
        owner_desc,
    ]
    if not apply:
        result.outcome = "dry-run（未执行）"
        return result
    success, outcome, changed = execute_fix_perms(resolved, recursive, uid, gid)
    result.applied = success
    result.outcome = outcome
    result.changed = changed
    return result


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="AIGCNEWS Tier-A 运维自愈动作（默认 dry-run，--apply 才执行）。"
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="真正执行动作；缺省仅打印计划（dry-run）",
    )
    parser.add_argument(
        "--audit-log",
        default=os.environ.get("AIGCNEWS_OPS_REMEDIATION_AUDIT", str(DEFAULT_AUDIT_LOG)),
        help="审计 JSONL 路径（默认 storage/metrics/ops_remediation_audit.jsonl）",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_restart = sub.add_parser("restart-container", help="重启应用层白名单容器")
    p_restart.add_argument("name", help="容器名（须在应用层白名单内）")

    p_perms = sub.add_parser("fix-storage-perms", help="修复 storage/ 下目录/文件权限")
    p_perms.add_argument("path", help="目标路径（须在仓库 storage/ 树内）")
    p_perms.add_argument("--recursive", action="store_true", help="递归处理子项")
    p_perms.add_argument(
        "--owner",
        default="",
        help="目标属主 uid[:gid] 或 user[:group]；缺省不改属主",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "restart-container":
        result = handle_restart(args.name, args.apply)
    elif args.command == "fix-storage-perms":
        result = handle_fix_perms(args.path, args.recursive, args.owner, args.apply)
    else:  # pragma: no cover - argparse required=True 已兜底
        print("unknown command", file=sys.stderr)
        return 2

    _append_audit(Path(args.audit_log), result)
    print(result.to_json())

    if not result.allowed:
        return 2
    if args.apply and not result.applied:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
