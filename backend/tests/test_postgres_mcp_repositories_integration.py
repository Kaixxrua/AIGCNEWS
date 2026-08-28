from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone

import pytest

from backend.app.core.postgres_database import (
    PostgresDatabaseLifecycle,
    create_postgres_pool,
)
from backend.app.core.postgres_migrations import PostgresMigrationRunner
from backend.app.domain.wechat_secret_box import WeChatSecretBox
from backend.app.repositories.mcp_server_repository import McpServerConfigConflictError
from backend.app.repositories.postgres_mcp_access_token_repository import (
    PostgresMcpAccessTokenRepository,
)
from backend.app.repositories.postgres_mcp_server_repository import (
    PostgresMcpServerConfigRepository,
)

pytestmark = pytest.mark.skipif(
    os.getenv("POSTGRES_INTEGRATION") != "1",
    reason="set POSTGRES_INTEGRATION=1 to run PostgreSQL integration tests",
)


@pytest.fixture
def database():
    lifecycle = PostgresDatabaseLifecycle(create_postgres_pool)
    lifecycle.open()
    PostgresMigrationRunner(lifecycle).apply()
    with lifecycle.transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute("TRUNCATE mcp_server_configs, users RESTART IDENTITY CASCADE")
    try:
        yield lifecycle
    finally:
        lifecycle.close()


def _create_user(database, email: str = "reader@example.com") -> int:
    with database.transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO users (email, hashed_password, role)
                VALUES (%s, 'hash', 'user')
                RETURNING id
                """,
                (email,),
            )
            return int(cursor.fetchone()["id"])


def test_postgres_mcp_server_repository_round_trip_and_unique_sqlstate(database) -> None:
    repository = PostgresMcpServerConfigRepository(
        database,
        (("seeded", "Seeded MCP", " https://seeded.example/mcp "),),
    )

    seeded = repository.list_mcp_server_configs()
    assert len(seeded) == 1
    assert seeded[0]["url"] == "https://seeded.example/mcp"
    assert seeded[0]["auth_token"] is None

    created = repository.create_mcp_server_config(
        {
            "server_key": " Private ",
            "display_name": " Private MCP ",
            "description": " initial ",
            "url": " https://private.example/mcp ",
            "auth_type": " BEARER ",
            "auth_token": " top-secret ",
            "enabled": False,
        }
    )
    assert created["server_key"] == "private"
    assert created["auth_token"] == "top-secret"
    assert created["enabled"] is False
    assert created["created_at"].tzinfo is not None

    preserved = repository.update_mcp_server_config(
        created["id"],
        {"display_name": "Renamed", "auth_token": "  "},
    )
    assert preserved["display_name"] == "Renamed"
    assert preserved["auth_token"] == "top-secret"

    tested = repository.update_mcp_server_test_result(
        created["id"],
        {"status": " SUCCEEDED ", "message": " ready ", "tools": [{"name": "搜索"}]},
    )
    assert tested["last_test_status"] == "succeeded"
    assert tested["last_test_message"] == "ready"
    assert "搜索" in tested["last_tools_json"]
    assert tested["last_test_at"].tzinfo is not None

    cleared = repository.update_mcp_server_config(
        created["id"], {"clear_auth_token": True}
    )
    assert cleared["auth_token"] is None

    with pytest.raises(McpServerConfigConflictError):
        repository.create_mcp_server_config(
            {
                "server_key": "private",
                "display_name": "Duplicate",
                "url": "https://duplicate.example/mcp",
            }
        )

    assert repository.delete_mcp_server_config(created["id"])
    assert repository.get_mcp_server_config(created["id"]) is None
    assert not repository.delete_mcp_server_config(created["id"])


def test_postgres_mcp_token_lifecycle_secrecy_expiry_and_unique_sqlstate(database) -> None:
    repository = PostgresMcpAccessTokenRepository(database)
    user_id = _create_user(database)
    future = datetime.now(timezone.utc) + timedelta(hours=1)

    created = repository.create_user_mcp_token(
        user_id=user_id,
        token_hash="a" * 64,
        token_hint="aigc_mcp_abc...wxyz",
        scopes=["projects:favorites:read"],
        client_type="claude",
        client_label="Desktop",
        expires_at=future,
    )
    metadata = created["token_metadata"]
    assert created["replaced_count"] == 0
    assert metadata["scopes"] == ["projects:favorites:read"]
    assert metadata["created_at"].endswith("Z")
    assert metadata["expires_at"].endswith("Z")
    assert "token_hash" not in metadata

    listed = repository.list_user_mcp_tokens(user_id=user_id)
    assert listed == [metadata]
    assert "token_hash" not in listed[0]

    authenticated = repository.get_user_by_mcp_token_hash("a" * 64)
    assert authenticated["user_id"] == user_id
    assert authenticated["email"] == "reader@example.com"
    assert authenticated["scopes"] == ["projects:favorites:read"]
    assert "token_hash" not in authenticated

    with pytest.raises(Exception) as context:
        repository.create_user_mcp_token(
            user_id=user_id,
            token_hash="a" * 64,
            token_hint="duplicate",
            scopes=[],
            client_type="claude",
        )
    assert getattr(context.value, "sqlstate", None) == "23505"

    expired = repository.create_user_mcp_token(
        user_id=user_id,
        token_hash="b" * 64,
        token_hint="expired",
        scopes=[],
        client_type="claude",
        expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
    )
    assert repository.get_user_by_mcp_token_hash("b" * 64) is None

    assert repository.delete_user_mcp_token(
        user_id=user_id,
        token_id=expired["token_metadata"]["id"],
    )
    assert not repository.delete_user_mcp_token(
        user_id=user_id,
        token_id=expired["token_metadata"]["id"],
    )
    assert repository.get_user_by_mcp_token_hash("b" * 64) is None
    assert all(item["id"] != expired["token_metadata"]["id"] for item in repository.list_user_mcp_tokens(user_id=user_id))


def test_postgres_mcp_token_rejects_missing_user(database) -> None:
    repository = PostgresMcpAccessTokenRepository(database)

    with pytest.raises(ValueError, match="user does not exist"):
        repository.create_user_mcp_token(
            user_id=999,
            token_hash="c" * 64,
            token_hint="missing",
            scopes=[],
            client_type="claude",
        )


def _dsh_material(box: WeChatSecretBox, token: str, hash_letter: str) -> dict:
    return {
        "token_hash": hash_letter * 64,
        "token_hint": f"{token[:12]}...{token[-4:]}",
        "token_encrypted": json.dumps(box.seal(token), ensure_ascii=False),
        "scopes": ["projects:favorites:read"],
        "client_type": "other",
        "client_label": "dsh-aigc-radar",
    }


def test_postgres_dsh_mcp_token_ensure_reuse_rotate_and_legacy_recovery(database) -> None:
    """0064 迁移 + DSH ensure/rotate 真实 PG 验证：

    首次 ensure 创建、重复 ensure 回显同一枚（库里仅一条活跃密封行）、
    legacy hash-only 行 recovery_required 且不被静默吊销、rotate 吊销旧
    DSH（旧 hash 立即失效）不碰 generic token、partial unique index 拒绝
    第二条活跃密封 DSH 行。
    """
    box = WeChatSecretBox.generate_for_test()
    repository = PostgresMcpAccessTokenRepository(database, secret_box=box)
    user_id = _create_user(database)

    first = repository.ensure_user_dsh_mcp_token(
        user_id=user_id, **_dsh_material(box, "aigc_mcp_first_token", "d")
    )
    assert first["status"] == "created"
    assert first["token"] == "aigc_mcp_first_token"
    assert first["token_metadata"]["purpose"] == "dsh"
    assert "token_encrypted" not in first["token_metadata"]
    assert "token_hash" not in first["token_metadata"]

    # 重复 ensure（模拟刷新/重开页面）：回显同一枚，不再 INSERT
    again = repository.ensure_user_dsh_mcp_token(
        user_id=user_id, **_dsh_material(box, "aigc_mcp_other_token", "e")
    )
    assert again["status"] == "reused"
    assert again["token"] == "aigc_mcp_first_token"
    assert again["token_metadata"]["id"] == first["token_metadata"]["id"]
    with database.transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) AS n FROM user_mcp_tokens WHERE user_id = %s AND purpose = 'dsh'",
                (user_id,),
            )
            assert int(cursor.fetchone()["n"]) == 1

    # DSH token 走与 generic 相同的 hash 鉴权路径（purpose 对鉴权透明）
    authenticated = repository.get_user_by_mcp_token_hash("d" * 64)
    assert authenticated is not None
    assert authenticated["user_id"] == user_id

    # partial unique index：第二条活跃密封 DSH 行被拒绝（并发 ensure 兜底）
    with pytest.raises(Exception) as conflict:
        with database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO user_mcp_tokens
                        (user_id, token_hash, token_hint, scopes_json, client_type,
                         client_label, expires_at, purpose, token_encrypted)
                    VALUES (%s, %s, 'dup', '[]', 'other', 'dsh-aigc-radar', NULL, 'dsh', %s)
                    """,
                    (user_id, "f" * 64, json.dumps(box.seal("aigc_mcp_dup"))),
                )
    assert getattr(conflict.value, "sqlstate", None) == "23505"

    # generic token 与 DSH 生命周期互不干扰
    generic = repository.create_user_mcp_token(
        user_id=user_id,
        token_hash="1" * 64,
        token_hint="generic",
        scopes=["projects:favorites:read"],
        client_type="claude",
    )
    rotated = repository.rotate_user_dsh_mcp_token(
        user_id=user_id, **_dsh_material(box, "aigc_mcp_rotated_token", "2")
    )
    assert rotated["status"] == "rotated"
    assert rotated["revoked_count"] == 1
    assert rotated["token"] == "aigc_mcp_rotated_token"
    # 旧 DSH hash 立即失效；generic token 不受影响
    assert repository.get_user_by_mcp_token_hash("d" * 64) is None
    generic_auth = repository.get_user_by_mcp_token_hash("1" * 64)
    assert generic_auth is not None
    assert generic_auth["user_id"] == user_id
    listed_ids = [item["id"] for item in repository.list_user_mcp_tokens(user_id=user_id)]
    assert generic["token_metadata"]["id"] in listed_ids
    assert rotated["token_metadata"]["id"] in listed_ids

    # legacy hash-only DSH 行（0064 一次性标记的历史数据）：ensure 不静默
    # 轮换，旧 token 继续可用；显式 rotate 才吊销
    legacy_user = _create_user(database, email="legacy@example.com")
    with database.transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO user_mcp_tokens
                    (user_id, token_hash, token_hint, scopes_json, client_type,
                     client_label, purpose)
                VALUES (%s, %s, 'legacy', '[]', 'other', 'dsh-aigc-radar', 'dsh')
                """,
                (legacy_user, "3" * 64),
            )
    legacy_ensure = repository.ensure_user_dsh_mcp_token(
        user_id=legacy_user, **_dsh_material(box, "aigc_mcp_legacy_new", "4")
    )
    assert legacy_ensure == {"status": "recovery_required", "legacy_count": 1}
    legacy_auth = repository.get_user_by_mcp_token_hash("3" * 64)
    assert legacy_auth is not None
    assert legacy_auth["user_id"] == legacy_user

    recovered = repository.rotate_user_dsh_mcp_token(
        user_id=legacy_user, **_dsh_material(box, "aigc_mcp_recovered", "5")
    )
    assert recovered["status"] == "rotated"
    assert recovered["revoked_count"] == 1
    assert repository.get_user_by_mcp_token_hash("3" * 64) is None
    assert repository.get_user_by_mcp_token_hash("5" * 64)["user_id"] == legacy_user
