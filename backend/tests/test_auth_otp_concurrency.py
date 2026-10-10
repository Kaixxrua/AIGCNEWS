import asyncio
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from backend.app.services.auth.account_lifecycle import AccountLifecycle, InvalidOtp
from backend.app.services.email.otp_store import OtpCooldownError, RedisOtpStore
from backend.app.services.email_service import EmailService
from backend.tests.otp_redis_fake import FakeRedis


class RacingRedis(FakeRedis):
    async def get(self, key):
        value = await super().get(key)
        # Both verifiers read the same snapshot before either gets to claim it.
        await asyncio.sleep(0)
        return value


@pytest.mark.asyncio
async def test_only_one_concurrent_verifier_can_claim_a_code():
    redis = RacingRedis()
    redis.values["email:reset:code:reader@example.com"] = "123456"
    store = RedisOtpStore(redis)
    results = await asyncio.gather(*(
        store.verify("reader@example.com", "123456", purpose="password_reset", consume=True)
        for _ in range(20)
    ))
    assert sum(results) == 1


@pytest.mark.asyncio
async def test_concurrent_password_resets_write_only_once():
    redis = RacingRedis()
    redis.values["email:reset:code:reader@example.com"] = "123456"
    repository = Mock()
    repository.get_user_by_email.return_value = {"id": 7}
    repository.update_user_password.return_value = 1
    lifecycle = AccountLifecycle(
        repository=repository, otp=EmailService(redis),
        hash_password=lambda password: password, verify_password=lambda *_: True,
        issue_token=lambda _: "token",
    )
    results = await asyncio.gather(*(
        lifecycle.reset_password(
            email="reader@example.com", email_code="123456", new_password=f"password-{index}",
        ) for index in range(10)
    ), return_exceptions=True)
    assert sum(isinstance(result, InvalidOtp) for result in results) == 9
    repository.update_user_password.assert_called_once()


@pytest.mark.asyncio
async def test_concurrent_sends_reserve_one_cooldown():
    store = RedisOtpStore(FakeRedis())
    results = await asyncio.gather(*(
        store.store("reader@example.com", str(index), purpose="registration")
        for index in range(10)
    ), return_exceptions=True)
    assert sum(isinstance(result, OtpCooldownError) for result in results) == 9


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["login", "register", "reset_password", "change_password", "setup_password"])
async def test_password_work_does_not_block_the_event_loop(operation):
    entered, released = threading.Event(), threading.Event()

    def password_work(*_):
        entered.set()
        assert released.wait(2), "password work blocked the event loop"
        return True if operation == "login" else "hash"

    repository = Mock()
    user = {"id": 7, "email": "reader@example.com", "hashed_password": "hash",
            "role": "user", "pwd_ver": 1, "password_login_enabled": operation != "setup_password"}
    repository.get_user_by_email.return_value = None if operation == "register" else user
    repository.get_user_by_id.return_value = user
    repository.update_user_password.return_value = 1
    repository.enable_password_login.return_value = user
    lifecycle = AccountLifecycle(
        repository=repository, otp=SimpleNamespace(verify_otp=AsyncMock(return_value=True)),
        hash_password=password_work, verify_password=password_work, issue_token=lambda _: "token",
    )
    arguments = {
        "login": dict(email=user["email"], password="password"),
        "register": dict(email=user["email"], email_code="123456", password="password", username="reader"),
        "reset_password": dict(email=user["email"], email_code="123456", new_password="password"),
        "change_password": dict(user_id=7, email_code="123456", new_password="password"),
        "setup_password": dict(user_id=7, email=user["email"], email_code="123456", new_password="password"),
    }
    pending = asyncio.create_task(getattr(lifecycle, operation)(**arguments[operation]))
    try:
        async with asyncio.timeout(1):
            while not entered.is_set():
                await asyncio.sleep(0.005)
        assert not pending.done()
    finally:
        released.set()
    await pending
