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

import hashlib
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

import pytest

from backend.tests.postgres_test_safety import postgres_test_sandbox

_TESTS_DIR = Path(__file__).resolve().parent
_IMPORT_CWD = Path.cwd()
os.chdir(_TESTS_DIR)
try:
    psycopg = pytest.importorskip("psycopg")
    pytest.importorskip("psycopg_pool")

    from backend.app.repositories.postgres_push_channel_repository import (
        PostgresPushChannelRepository,
    )
    from backend.app.repositories.postgres_push_delivery_repository import (
        PostgresPushDeliveryRepository,
    )
    from backend.app.repositories.postgres_telegram_link_attempt_repository import (
        PostgresTelegramLinkAttemptRepository,
    )
    from backend.app.repositories.postgres_user_subscription_repository import (
        PostgresUserSubscriptionRepository,
    )
finally:
    os.chdir(_IMPORT_CWD)


@pytest.fixture(scope="module")
def database() -> Iterator[Any]:
    with postgres_test_sandbox() as sandbox:
        database = sandbox.database
        yield database


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
            "INSERT INTO user_subscriptions (user_id, channel_id) VALUES (%s, %s) RETURNING id",
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
    assert not repository.set_channel_status(user_id=other_id, channel_id=channel_id, status="disabled")
    assert not repository.delete_channel(user_id=other_id, channel_id=channel_id)

    assert repository.mark_channel_verified(user_id=owner_id, channel_id=channel_id)
    assert repository.set_channel_status(user_id=owner_id, channel_id=channel_id, status="disabled")
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
        repository.set_channel_status(user_id=user_id, channel_id=int(channel["id"]), status="archived")

    # 约束失败后连接已被事务上下文安全弃用，后续操作不受影响
    assert repository.get_channel(user_id=user_id, channel_id=int(channel["id"])) is not None


def test_push_delivery_create_is_idempotent_and_defaults_pending(database) -> None:
    repository = PostgresPushDeliveryRepository(database)
    user_id = _create_user(database)
    channel = _create_channel(database, user_id)
    subscription_id = _create_subscription(database, user_id=user_id, channel_id=int(channel["id"]))

    delivery = repository.create_delivery(subscription_id=subscription_id, item_key="2026-08-08")
    assert delivery is not None
    assert delivery["status"] == "pending"
    assert delivery["attempts"] == 0
    assert delivery["last_error"] is None
    assert delivery["sent_at"] is None

    # uq_push_deliveries_subscription_item 冲突（并发重复派发）返回 None
    assert repository.create_delivery(subscription_id=subscription_id, item_key="2026-08-08") is None
    fetched = repository.get_delivery(subscription_id=subscription_id, item_key="2026-08-08")
    assert fetched is not None and int(fetched["id"]) == int(delivery["id"])
    assert repository.get_delivery(subscription_id=subscription_id, item_key="missing") is None


def test_push_delivery_sent_transition_only_from_pending(database) -> None:
    repository = PostgresPushDeliveryRepository(database)
    user_id = _create_user(database)
    channel = _create_channel(database, user_id)
    subscription_id = _create_subscription(database, user_id=user_id, channel_id=int(channel["id"]))
    delivery = repository.create_delivery(subscription_id=subscription_id, item_key="2026-08-08")
    assert delivery is not None
    delivery_id = int(delivery["id"])

    repository.mark_delivery_sent(delivery_id=delivery_id, attempts=2)
    sent = repository.get_delivery(subscription_id=subscription_id, item_key="2026-08-08")
    assert sent is not None
    assert sent["status"] == "sent"
    assert sent["attempts"] == 2
    assert sent["sent_at"] is not None
    assert sent["last_error"] is None

    # 并发派发下第二个 worker 的 sent 迁移不再生效：attempts/sent_at 保持首次值
    repository.mark_delivery_sent(delivery_id=delivery_id, attempts=5)
    still = repository.get_delivery(subscription_id=subscription_id, item_key="2026-08-08")
    assert still is not None
    assert still["attempts"] == 2
    assert still["sent_at"] == sent["sent_at"]


def test_push_delivery_failed_attempts_and_terminal_state(database) -> None:
    repository = PostgresPushDeliveryRepository(database)
    user_id = _create_user(database)
    channel = _create_channel(database, user_id)
    subscription_id = _create_subscription(database, user_id=user_id, channel_id=int(channel["id"]))
    delivery = repository.create_delivery(subscription_id=subscription_id, item_key="2026-08-08")
    assert delivery is not None
    delivery_id = int(delivery["id"])

    # 未用尽重试次数：保持 pending，记录错误供下一次派发读取
    repository.record_attempt_failed(delivery_id=delivery_id, attempts=1, last_error="smtp timeout", exhausted=False)
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
    repository.record_attempt_failed(delivery_id=delivery_id, attempts=5, last_error="late", exhausted=False)
    row = repository.get_delivery(subscription_id=subscription_id, item_key="2026-08-08")
    assert row is not None
    assert row["status"] == "failed"
    assert row["attempts"] == 3
    assert row["sent_at"] is None


def test_push_delivery_requires_existing_subscription(database) -> None:
    repository = PostgresPushDeliveryRepository(database)
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        repository.create_delivery(subscription_id=999_999_999, item_key="orphan")


def test_count_email_deliveries_by_day_scopes_channel_and_window(database) -> None:
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    repository = PostgresPushDeliveryRepository(database)
    user_id = _create_user(database)
    email_channel = _create_channel(database, user_id)
    webhook_channel = _create_channel(
        database,
        user_id,
        target=f"https://example.com/hook-{uuid.uuid4().hex}",
        channel_type="webhook",
    )
    email_subscription_id = _create_subscription(database, user_id=user_id, channel_id=int(email_channel["id"]))
    webhook_subscription_id = _create_subscription(database, user_id=user_id, channel_id=int(webhook_channel["id"]))

    # 模块共享 schema：前面用例已留下 sent/failed 的 email 投递，
    # 先取基线，后面按增量断言
    baseline_14d = {row["date"]: row for row in repository.count_email_deliveries_by_day(days=14)}

    # email 渠道：两条 sent + 一条 failed 终态，全部归今日（Asia/Shanghai）
    for item_key in ("item-a", "item-b"):
        delivery = repository.create_delivery(subscription_id=email_subscription_id, item_key=item_key)
        assert delivery is not None
        repository.mark_delivery_sent(delivery_id=int(delivery["id"]), attempts=1)
    failed = repository.create_delivery(subscription_id=email_subscription_id, item_key="item-c")
    assert failed is not None
    repository.record_attempt_failed(
        delivery_id=int(failed["id"]),
        attempts=3,
        last_error="smtp rejected",
        exhausted=True,
    )
    # pending 不计入统计
    assert repository.create_delivery(subscription_id=email_subscription_id, item_key="item-pending") is not None

    # webhook 渠道的 sent 不计入 email 统计
    webhook_delivery = repository.create_delivery(subscription_id=webhook_subscription_id, item_key="item-hook")
    assert webhook_delivery is not None
    repository.mark_delivery_sent(delivery_id=int(webhook_delivery["id"]), attempts=1)

    # 10 天前的 sent：days=7 窗口外、days=14 窗口内
    old = repository.create_delivery(subscription_id=email_subscription_id, item_key="item-old")
    assert old is not None
    repository.mark_delivery_sent(delivery_id=int(old["id"]), attempts=1)
    with database.transaction() as connection:
        connection.execute(
            "UPDATE push_deliveries SET sent_at = CURRENT_TIMESTAMP - INTERVAL '10 days' WHERE id = %s",
            (int(old["id"]),),
        )

    shanghai_today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
    today = shanghai_today.isoformat()
    old_day = (shanghai_today - timedelta(days=10)).isoformat()

    stats_7d = repository.count_email_deliveries_by_day(days=7)
    by_day_7d = {row["date"]: row for row in stats_7d}
    base_today = baseline_14d.get(today, {"sent": 0, "failed": 0})
    # 增量恰好 +2 sent / +1 failed：pending 与 webhook 行均未混入
    assert by_day_7d[today]["sent"] == base_today["sent"] + 2
    assert by_day_7d[today]["failed"] == base_today["failed"] + 1
    # 7 天窗口剔除 10 天前的 sent
    assert old_day not in by_day_7d

    stats_14d = repository.count_email_deliveries_by_day(days=14)
    by_day_14d = {row["date"]: row for row in stats_14d}
    base_old = baseline_14d.get(old_day, {"sent": 0, "failed": 0})
    assert by_day_14d[old_day]["sent"] == base_old["sent"] + 1
    # 结果按日期倒序
    assert [row["date"] for row in stats_14d] == sorted((row["date"] for row in stats_14d), reverse=True)


def _create_member_user(database: Any, *, tier: str = "member", role: str = "user") -> int:
    with database.transaction() as connection:
        row = connection.execute(
            "INSERT INTO users (email, hashed_password, role, membership_tier) VALUES (%s, %s, %s, %s) RETURNING id",
            (f"push-it-{uuid.uuid4().hex}@example.com", "hash", role, tier),
        ).fetchone()
        return int(row["id"])


def test_push_channel_provider_key_cross_user_conflict_returns_none(database) -> None:
    """0060：provider_key 部分唯一索引跨用户兜底；冲突返回 None 而非抛错。"""
    channels = PostgresPushChannelRepository(database)
    owner_id, other_id = _create_user(database), _create_user(database)
    key = f"pk-{uuid.uuid4().hex}"

    first = channels.create_channel(
        user_id=owner_id,
        channel_type="telegram",
        target=f"tg-{uuid.uuid4().hex}",
        encrypted_config="sealed",
        verified=True,
        provider_key=key,
        display_target="Telegram 私聊 · ****2001",
    )
    assert first is not None
    assert first["provider_key"] == key
    assert first["display_target"] == "Telegram 私聊 · ****2001"

    # 跨用户同 (channel_type, provider_key)：唯一索引兜底，静默拒绝
    duplicate = channels.create_channel(
        user_id=other_id,
        channel_type="telegram",
        target=f"tg-{uuid.uuid4().hex}",
        encrypted_config="sealed",
        verified=True,
        provider_key=key,
        display_target="other",
    )
    assert duplicate is None

    found = channels.find_channel_by_provider_key(channel_type="telegram", provider_key=key)
    assert found is not None
    assert found["user_id"] == owner_id

    # 不同 channel_type 同 key 不冲突（索引按 (channel_type, provider_key)）
    other_type = channels.create_channel(
        user_id=other_id,
        channel_type="discord",
        target=f"dg-{uuid.uuid4().hex}",
        encrypted_config="sealed",
        verified=True,
        provider_key=key,
        display_target="discord",
    )
    assert other_type is not None
    assert channels.find_channel_by_provider_key(channel_type="discord", provider_key=key)["user_id"] == other_id
    # 未登记的类型查不到
    assert channels.find_channel_by_provider_key(channel_type="webhook", provider_key=key) is None


def test_telegram_link_attempt_lifecycle(database) -> None:
    attempts = PostgresTelegramLinkAttemptRepository(database)
    channels = PostgresPushChannelRepository(database)
    user_id, other_id = _create_user(database), _create_user(database)
    attempt_id = uuid.uuid4()
    nonce_hash = hashlib.sha256(b"nonce-a").hexdigest()
    expires = datetime.now(timezone.utc) + timedelta(minutes=5)

    created = attempts.create_attempt(
        attempt_id=attempt_id,
        user_id=user_id,
        nonce_hash=nonce_hash,
        expires_at=expires,
    )
    assert created["status"] == "pending"

    # owner 范围查询；读取不回放 nonce_hash
    assert attempts.get_attempt(user_id=other_id, attempt_id=attempt_id) is None
    fetched = attempts.get_attempt(user_id=user_id, attempt_id=attempt_id)
    assert fetched is not None
    assert "nonce_hash" not in fetched

    # 错误哈希不命中；正确哈希原子消费并记录 chat_id
    assert attempts.consume_attempt(nonce_hash=hashlib.sha256(b"wrong").hexdigest(), chat_id="1") is None
    consumed = attempts.consume_attempt(nonce_hash=nonce_hash, chat_id="424242001")
    assert consumed is not None
    assert consumed["status"] == "completed"
    assert consumed["user_id"] == user_id
    # 单次语义：二次消费被拒
    assert attempts.consume_attempt(nonce_hash=nonce_hash, chat_id="424242001") is None

    channel = channels.create_channel(
        user_id=user_id,
        channel_type="telegram",
        target=f"tg-{uuid.uuid4().hex}",
        encrypted_config="sealed",
        verified=True,
        provider_key=f"pk-{uuid.uuid4().hex}",
        display_target="Telegram 私聊 · ****2001",
    )
    assert channel is not None
    attempts.attach_channel(attempt_id=attempt_id, channel_id=int(channel["id"]))
    after = attempts.get_attempt(user_id=user_id, attempt_id=attempt_id)
    assert after is not None
    assert int(after["channel_id"]) == int(channel["id"])
    assert after["status"] == "completed"


def test_telegram_link_attempt_expired_cannot_consume(database) -> None:
    attempts = PostgresTelegramLinkAttemptRepository(database)
    user_id = _create_user(database)
    attempt_id = uuid.uuid4()
    nonce_hash = hashlib.sha256(b"expired-nonce").hexdigest()
    attempts.create_attempt(
        attempt_id=attempt_id,
        user_id=user_id,
        nonce_hash=nonce_hash,
        expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
    )
    assert attempts.consume_attempt(nonce_hash=nonce_hash, chat_id="1") is None
    # 过期未被消费的 attempt 仍保持 pending（状态查询侧按 expires_at 呈现 expired）
    fetched = attempts.get_attempt(user_id=user_id, attempt_id=attempt_id)
    assert fetched is not None and fetched["status"] == "pending"


def test_telegram_link_attempt_consume_single_winner_under_concurrency(database) -> None:
    """并发回调同一 nonce：原子 UPDATE 保证恰好一个赢家。"""
    attempts = PostgresTelegramLinkAttemptRepository(database)
    user_id = _create_user(database)
    attempt_id = uuid.uuid4()
    nonce_hash = hashlib.sha256(b"race-nonce").hexdigest()
    attempts.create_attempt(
        attempt_id=attempt_id,
        user_id=user_id,
        nonce_hash=nonce_hash,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
    )

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(
            pool.map(
                lambda _: attempts.consume_attempt(nonce_hash=nonce_hash, chat_id="424242001"),
                range(8),
            )
        )
    winners = [row for row in results if row is not None]
    assert len(winners) == 1
    assert winners[0]["attempt_id"] == attempt_id


def test_list_active_dispatchable_carries_membership_fields(database) -> None:
    """派发查询联表 users：带出 role/membership_tier/membership_expires_at。"""
    channels = PostgresPushChannelRepository(database)
    subscriptions = PostgresUserSubscriptionRepository(database)
    user_id = _create_member_user(database, tier="member")
    channel = channels.create_channel(
        user_id=user_id,
        channel_type="webhook",
        target=f"https://example.com/hook-{uuid.uuid4().hex}",
        encrypted_config="sealed",
        verified=True,
    )
    assert channel is not None
    subscription_id = _create_subscription(database, user_id=user_id, channel_id=int(channel["id"]))

    rows = subscriptions.list_active_dispatchable(frequency="daily")
    mine = [row for row in rows if int(row["id"]) == subscription_id]
    assert len(mine) == 1
    row = mine[0]
    assert row["role"] == "user"
    assert row["membership_tier"] == "member"
    assert "membership_expires_at" in row
    assert row["encrypted_config"] == "sealed"
