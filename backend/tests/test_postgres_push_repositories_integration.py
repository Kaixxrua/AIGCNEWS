"""push_channels / push_deliveries 两个 PostgreSQL 仓储的真库集成测试。

此前这两个仓储的 SQL 只经 Fake 契约测试覆盖，从未对真实库验证。
这里用 TEST_POSTGRES_DSN 门控 + 每模块独立 scratch schema 的既有模式
（与 test_postgres_config_repositories_integration.py 相同）覆盖：

- 渠道：建 / 查 / 列表 / 更新（verified、status）/ 删除、属主隔离、
  唯一约束冲突返回 None、CHECK 约束拒绝非法枚举值；
- 投递：创建幂等（ON CONFLICT 返回 None）、pending → sent/failed 的
  单向状态迁移（终态不可再迁移）、失败重试记录、last_error 截断、
  外键约束（subscription 必须存在）。
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any, Iterator

import pytest

_TESTS_DIR = Path(__file__).resolve().parent
_IMPORT_CWD = Path.cwd()
os.chdir(_TESTS_DIR)
try:
    psycopg = pytest.importorskip("psycopg")
    pytest.importorskip("psycopg_pool")
    from psycopg.conninfo import conninfo_to_dict, make_conninfo
    from psycopg_pool import ConnectionPool

    from backend.app.core.postgres_database import PostgresDatabaseLifecycle
    from backend.app.core.postgres_migrations import PostgresMigrationRunner
    from backend.app.repositories.postgres_push_channel_repository import (
        PostgresPushChannelRepository,
    )
    from backend.app.repositories.postgres_push_delivery_repository import (
        PostgresPushDeliveryRepository,
    )
finally:
    os.chdir(_IMPORT_CWD)


def _test_dsn() -> str:
    dsn = os.environ.get("TEST_POSTGRES_DSN", "").strip()
    if not dsn:
        pytest.skip("TEST_POSTGRES_DSN is required for PostgreSQL integration tests")
    try:
        database = str(conninfo_to_dict(dsn).get("dbname") or "")
    except Exception as exc:
        pytest.skip(f"TEST_POSTGRES_DSN is not a valid PostgreSQL DSN: {exc}")
    if "test" not in database.lower():
        pytest.skip("TEST_POSTGRES_DSN dbname must contain 'test'")
    return dsn


@pytest.fixture(scope="module")
def database() -> Iterator[Any]:
    dsn = _test_dsn()
    schema = f"push_it_{uuid.uuid4().hex}"
    with psycopg.connect(dsn, autocommit=True) as admin:
        admin.execute(f'CREATE SCHEMA "{schema}"')

    scoped_dsn = make_conninfo(dsn, options=f"-c search_path={schema}")
    lifecycle = PostgresDatabaseLifecycle(
        lambda: ConnectionPool(
            conninfo=scoped_dsn,
            min_size=1,
            max_size=4,
            timeout=10,
            kwargs={"autocommit": False, "row_factory": psycopg.rows.dict_row},
            open=False,
        )
    )
    try:
        PostgresMigrationRunner(lifecycle).apply()
        yield lifecycle
    finally:
        lifecycle.close()
        with psycopg.connect(dsn, autocommit=True) as admin:
            admin.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')


def _create_user(database: Any) -> int:
    with database.transaction() as connection:
        row = connection.execute(
            "INSERT INTO users (email, hashed_password) VALUES (%s, %s) RETURNING id",
            (f"push-it-{uuid.uuid4().hex}@example.com", "hash"),
        ).fetchone()
        return int(row["id"])


def _create_subscription(database: Any, *, user_id: int, channel_id: int) -> int:
    with database.transaction() as connection:
        row = connection.execute(
            "INSERT INTO user_subscriptions (user_id, channel_id)"
            " VALUES (%s, %s) RETURNING id",
            (user_id, channel_id),
        ).fetchone()
        return int(row["id"])


def _create_channel(
    database: Any,
    user_id: int,
    *,
    target: str | None = None,
    channel_type: str = "email",
) -> dict[str, Any]:
    repository = PostgresPushChannelRepository(database)
    channel = repository.create_channel(
        user_id=user_id,
        channel_type=channel_type,
        target=target or f"target-{uuid.uuid4().hex}@example.com",
        encrypted_config="sealed-config",
    )
    assert channel is not None
    return channel


def test_push_channel_round_trip_update_and_owner_scoping(database) -> None:
    repository = PostgresPushChannelRepository(database)
    owner_id, other_id = _create_user(database), _create_user(database)

    channel = _create_channel(database, owner_id)
    channel_id = int(channel["id"])
    assert channel["verified"] is False
    assert channel["status"] == "active"
    assert channel["encrypted_config"] == "sealed-config"

    second = _create_channel(database, owner_id)
    assert [row["id"] for row in repository.list_channels(owner_id)] == [
        channel_id,
        int(second["id"]),
    ]
    assert repository.list_channels(other_id) == []

    found = repository.find_channel_by_target(
        user_id=owner_id,
        channel_type="email",
        target=channel["target"],
    )
    assert found is not None and int(found["id"]) == channel_id
    assert repository.get_channel(user_id=owner_id, channel_id=channel_id) is not None

    # 属主隔离：其他用户读不到、也改不动这条渠道
    assert repository.get_channel(user_id=other_id, channel_id=channel_id) is None
    assert not repository.mark_channel_verified(user_id=other_id, channel_id=channel_id)
    assert not repository.set_channel_status(
        user_id=other_id, channel_id=channel_id, status="disabled"
    )
    assert not repository.delete_channel(user_id=other_id, channel_id=channel_id)

    assert repository.mark_channel_verified(user_id=owner_id, channel_id=channel_id)
    assert repository.set_channel_status(
        user_id=owner_id, channel_id=channel_id, status="disabled"
    )
    updated = repository.get_channel(user_id=owner_id, channel_id=channel_id)
    assert updated is not None
    assert updated["verified"] is True
    assert updated["status"] == "disabled"

    assert repository.delete_channel(user_id=owner_id, channel_id=channel_id)
    assert repository.get_channel(user_id=owner_id, channel_id=channel_id) is None
    assert not repository.delete_channel(user_id=owner_id, channel_id=channel_id)


def test_push_channel_create_conflict_returns_none(database) -> None:
    repository = PostgresPushChannelRepository(database)
    user_id = _create_user(database)

    first = repository.create_channel(
        user_id=user_id,
        channel_type="webhook",
        target="https://example.com/hook",
        encrypted_config=None,
        verified=True,
    )
    assert first is not None
    assert first["verified"] is True
    assert first["encrypted_config"] is None

    # uq_push_channels_user_type_target 冲突走 ON CONFLICT DO NOTHING，
    # 仓储以 None 告知调用方（服务层据此报重复渠道）。
    duplicate = repository.create_channel(
        user_id=user_id,
        channel_type="webhook",
        target="https://example.com/hook",
        encrypted_config="other",
    )
    assert duplicate is None
    assert len(repository.list_channels(user_id)) == 1


def test_push_channel_check_constraints_reject_unknown_enums(database) -> None:
    repository = PostgresPushChannelRepository(database)
    user_id = _create_user(database)

    # ck_push_channels_type 只允许 email / webhook
    with pytest.raises(psycopg.errors.CheckViolation):
        repository.create_channel(
            user_id=user_id,
            channel_type="sms",
            target="+8613800000000",
            encrypted_config=None,
        )

    channel = _create_channel(database, user_id)
    # ck_push_channels_status 只允许 active / disabled
    with pytest.raises(psycopg.errors.CheckViolation):
        repository.set_channel_status(
            user_id=user_id, channel_id=int(channel["id"]), status="archived"
        )

    # 约束失败后连接已被事务上下文安全弃用，后续操作不受影响
    assert repository.get_channel(user_id=user_id, channel_id=int(channel["id"])) is not None


def test_push_delivery_create_is_idempotent_and_defaults_pending(database) -> None:
    repository = PostgresPushDeliveryRepository(database)
    user_id = _create_user(database)
    channel = _create_channel(database, user_id)
    subscription_id = _create_subscription(
        database, user_id=user_id, channel_id=int(channel["id"])
    )

    delivery = repository.create_delivery(
        subscription_id=subscription_id, item_key="2026-08-08"
    )
    assert delivery is not None
    assert delivery["status"] == "pending"
    assert delivery["attempts"] == 0
    assert delivery["last_error"] is None
    assert delivery["sent_at"] is None

    # uq_push_deliveries_subscription_item 冲突（并发重复派发）返回 None
    assert (
        repository.create_delivery(subscription_id=subscription_id, item_key="2026-08-08")
        is None
    )
    fetched = repository.get_delivery(
        subscription_id=subscription_id, item_key="2026-08-08"
    )
    assert fetched is not None and int(fetched["id"]) == int(delivery["id"])
    assert (
        repository.get_delivery(subscription_id=subscription_id, item_key="missing")
        is None
    )


def test_push_delivery_sent_transition_only_from_pending(database) -> None:
    repository = PostgresPushDeliveryRepository(database)
    user_id = _create_user(database)
    channel = _create_channel(database, user_id)
    subscription_id = _create_subscription(
        database, user_id=user_id, channel_id=int(channel["id"])
    )
    delivery = repository.create_delivery(
        subscription_id=subscription_id, item_key="2026-08-08"
    )
    assert delivery is not None
    delivery_id = int(delivery["id"])

    repository.mark_delivery_sent(delivery_id=delivery_id, attempts=2)
    sent = repository.get_delivery(
        subscription_id=subscription_id, item_key="2026-08-08"
    )
    assert sent is not None
    assert sent["status"] == "sent"
    assert sent["attempts"] == 2
    assert sent["sent_at"] is not None
    assert sent["last_error"] is None

    # 并发派发下第二个 worker 的 sent 迁移不再生效：attempts/sent_at 保持首次值
    repository.mark_delivery_sent(delivery_id=delivery_id, attempts=5)
    still = repository.get_delivery(
        subscription_id=subscription_id, item_key="2026-08-08"
    )
    assert still is not None
    assert still["attempts"] == 2
    assert still["sent_at"] == sent["sent_at"]


def test_push_delivery_failed_attempts_and_terminal_state(database) -> None:
    repository = PostgresPushDeliveryRepository(database)
    user_id = _create_user(database)
    channel = _create_channel(database, user_id)
    subscription_id = _create_subscription(
        database, user_id=user_id, channel_id=int(channel["id"])
    )
    delivery = repository.create_delivery(
        subscription_id=subscription_id, item_key="2026-08-08"
    )
    assert delivery is not None
    delivery_id = int(delivery["id"])

    # 未用尽重试次数：保持 pending，记录错误供下一次派发读取
    repository.record_attempt_failed(
        delivery_id=delivery_id, attempts=1, last_error="smtp timeout", exhausted=False
    )
    row = repository.get_delivery(subscription_id=subscription_id, item_key="2026-08-08")
    assert row is not None
    assert row["status"] == "pending"
    assert row["attempts"] == 1
    assert row["last_error"] == "smtp timeout"

    # 用尽后进入 failed 终态；超长错误按仓储约定截断到 2000 字符
    repository.record_attempt_failed(
        delivery_id=delivery_id,
        attempts=3,
        last_error="x" * 3000,
        exhausted=True,
    )
    row = repository.get_delivery(subscription_id=subscription_id, item_key="2026-08-08")
    assert row is not None
    assert row["status"] == "failed"
    assert row["attempts"] == 3
    assert len(row["last_error"]) == 2000

    # 终态不可逆：sent / 再次失败记录都不再生效
    repository.mark_delivery_sent(delivery_id=delivery_id, attempts=4)
    repository.record_attempt_failed(
        delivery_id=delivery_id, attempts=5, last_error="late", exhausted=False
    )
    row = repository.get_delivery(subscription_id=subscription_id, item_key="2026-08-08")
    assert row is not None
    assert row["status"] == "failed"
    assert row["attempts"] == 3
    assert row["sent_at"] is None


def test_push_delivery_requires_existing_subscription(database) -> None:
    repository = PostgresPushDeliveryRepository(database)
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        repository.create_delivery(subscription_id=999_999_999, item_key="orphan")
