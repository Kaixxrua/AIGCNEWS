from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COMPOSE_PATH = ROOT / "docker" / "docker-compose.yml"
SCRIPT_PATH = ROOT / "scripts" / "manage_main_stack.sh"
UNIT_PATH = ROOT / "deploy" / "systemd" / "aigcnews-compose@.service"


def test_main_compose_has_health_gated_boot_contract() -> None:
    text = COMPOSE_PATH.read_text(encoding="utf-8")

    assert text.startswith("name: docker\n")
    for service in ("etcd", "minio", "milvus", "attu", "neo4j"):
        assert re.search(
            rf"^  {service}:\n(?:(?:    |$).*\n)*?    restart: unless-stopped$",
            text,
            re.MULTILINE,
        )
    assert "http://127.0.0.1:9091/healthz" in text
    assert "http://127.0.0.1:8000/api/ready" in text
    for mysql_runtime_marker in (
        "mysql-aigc",
        "mysqladmin",
        '"3306:3306"',
        "mysql_data",
    ):
        assert mysql_runtime_marker not in text
    assert '["CMD", "redis-cli", "ping"]' in text
    # 核心栈 10 处健康门控（backend-api×3 + mcp-api-go×3 + frontend-web×1 +
    # milvus×2 + attu×1）；Python 独立 MCP 进程 mcp-api×3 已随 W6-U3 移除，
    # 原 frontend-web → priceai 一处随 priceai 服务迁至私有 overlay
    # （../aigcnews_private/deploy/docker-compose.private.yml）
    assert text.count("condition: service_healthy") == 10
    backend_dependencies = text.split("  backend-api:", 1)[1].split(
        "\n  project-catalog-postgres:\n", 1
    )[0]
    for dependency in ("redis", "milvus", "project-catalog-postgres"):
        assert f"      {dependency}:\n        condition: service_healthy" in backend_dependencies
    # 独立 MCP 进程（mcp-api / mcp_main）已退役：服务块与健康门控不得再出现；
    # 工具调用计数由 Go 网关直写 Redis，无单写者 JSON 分目录需求
    assert "  mcp-api:" not in text
    assert "mcp_main" not in text
    assert "MCP_TOOL_CALL_METRICS_PATH=storage/metrics_mcp/" not in text
    assert "./volumes/etcd:/etcd" in text
    assert "./volumes/minio:/minio_data" in text
    assert "./volumes/milvus:/var/lib/milvus" in text
    # 姊妹服务（priceai）及其 Supabase 环境要求已迁至私有 overlay；
    # 核心栈不得再耦合其环境变量，overlay 注入点由头部注释锚定
    assert "../aigcnews_private/deploy/docker-compose.private.yml" in text
    assert "NEXT_PUBLIC_SUPABASE" not in text


def test_main_stack_orchestrator_has_static_safety_guards() -> None:
    text = SCRIPT_PATH.read_text(encoding="utf-8")

    assert "set -Eeuo pipefail" in text
    assert '--project-name "${EXPECTED_PROJECT}"' in text
    assert "compose config --quiet" in text
    assert "--remove-orphans --no-build --pull never --wait --wait-timeout 300" in text
    assert '--env-file "${APP_ENV_FILE}"' in text
    assert '--env-file "${PRICEAI_ENV_FILE}"' in text
    assert 'ensure_profile "mcp-go"' in text
    assert 'ensure_profile "dailyhot"' in text
    assert "ensure_required_profiles" in text
    assert "sudo" not in text
    assert "down --volumes" not in text
    assert "down -v" not in text
    assert "volume rm" not in text
    assert "volume prune" not in text


def test_main_stack_systemd_unit_is_non_destructive() -> None:
    text = UNIT_PATH.read_text(encoding="utf-8")

    assert "Requires=docker.service" in text
    assert "After=docker.service network-online.target" in text
    assert "Type=oneshot" in text
    assert "RemainAfterExit=yes" in text
    assert "User=%i" in text
    assert "EnvironmentFile=/home/%i/AIGCNEWS/.env" in text
    assert "EnvironmentFile=/home/%i/.priceai-node.env" in text
    assert "scripts/manage_main_stack.sh up" in text
    assert "WantedBy=multi-user.target" in text
    assert "ExecStop=" not in text


def test_main_stack_orchestrator_shell_syntax() -> None:
    subprocess.run(["bash", "-n", str(SCRIPT_PATH)], check=True)


def test_main_stack_provisions_storage_bind_dirs_before_containers() -> None:
    """storage 绑定源目录须在起容器前由部署用户预建，杜绝 docker 以 root 代建
    导致容器内 app(uid 1000) 写入 [Errno 13]。清单须与 compose 的 ../storage
    绑定源一致，且在 up 与 migrate 两条起容器路径上都调用。"""
    text = SCRIPT_PATH.read_text(encoding="utf-8")
    compose = COMPOSE_PATH.read_text(encoding="utf-8")

    assert "ensure_storage_dirs()" in text
    # 每个 compose ../storage 绑定源都必须出现在预建清单里
    for rel in re.findall(r"\.\./(storage/[\w./-]+):", compose):
        assert f'"{rel}"' in text, f"预建清单缺少 compose 绑定源 {rel}"

    # up 与 migrate 都在 compose 起容器前调用预建
    for action in ("up", "migrate"):
        block = text.split(f"    {action})", 1)[1].split(";;", 1)[0]
        assert "ensure_storage_dirs" in block, f"{action} 未预建 storage 目录"
        assert block.index("ensure_storage_dirs") < block.index("compose ")


def test_ensure_storage_dirs_creates_dirs_owned_by_deploy_user(tmp_path: Path) -> None:
    """实际执行 ensure_storage_dirs：目录被创建且属主为当前（部署）用户。

    source 一份临时副本以只加载函数、不触发编排（脚本尾部有 source guard）。
    ROOT_DIR 由副本位置推导，故落到 tmp_path 下。"""
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    shutil.copy(SCRIPT_PATH, scripts_dir / "manage_main_stack.sh")

    result = subprocess.run(
        ["bash", "-c", f'source "{scripts_dir / "manage_main_stack.sh"}"; ensure_storage_dirs'],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr

    for rel in (
        "storage/papers",
        "storage/site",
        "storage/chat_uploads",
        "storage/metrics",
        "storage/x_media",
        "storage/wechat",
        "storage/hf_cache/huggingface",
    ):
        created = tmp_path / rel
        assert created.is_dir(), f"{rel} 未创建"
        assert created.stat().st_uid == os.getuid(), f"{rel} 属主非部署用户"

    # 幂等：再跑一次不报错，也不改变结果
    again = subprocess.run(
        ["bash", "-c", f'source "{scripts_dir / "manage_main_stack.sh"}"; ensure_storage_dirs'],
        capture_output=True,
        text=True,
    )
    assert again.returncode == 0, again.stderr
