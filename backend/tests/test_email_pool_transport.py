from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from aiosmtplib.errors import SMTPResponseException

from backend.app.services.email import pool_transport
from backend.app.services.email.pool_transport import (
    EmailPoolEntry,
    EmailPoolQuotaStore,
    EmailPoolTransport,
    is_quota_error,
    parse_email_pool_entries,
)
from backend.app.services.email.smtp_transport import SmtpDeliveryError
from backend.app.services.email_service import build_email_service

FIXED_NOW = datetime(2026, 8, 14, 12, 0, 0, tzinfo=timezone.utc)


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, object] = {}
        self.expirations: dict[str, int] = {}

    async def get(self, key: str):
        return self.values.get(key)

    async def set(self, key: str, value: object, *, ex: int | None = None):
        self.values[key] = value
        if ex is not None:
            self.expirations[key] = ex

    async def incr(self, key: str) -> int:
        value = int(self.values.get(key, 0)) + 1
        self.values[key] = value
        return value

    async def expire(self, key: str, seconds: int):
        self.expirations[key] = seconds


class ExplodingRedis:
    async def get(self, key: str):
        raise ConnectionError("redis down")

    async def set(self, key: str, value: object, *, ex: int | None = None):
        raise ConnectionError("redis down")

    async def incr(self, key: str) -> int:
        raise ConnectionError("redis down")

    async def expire(self, key: str, seconds: int):
        raise ConnectionError("redis down")


class FakeEntryTransport:
    """按 host 区分 entry 的假 SmtpTransport；fail_with 配置抛错脚本。"""

    calls: list[tuple[str, str, str, str]] = []
    fail_with: dict[str, Exception] = {}

    def __init__(self, *, host: str, from_email: str, **kwargs) -> None:
        self.host = host
        self.from_email = from_email

    @classmethod
    def reset(cls) -> None:
        cls.calls = []
        cls.fail_with = {}

    @classmethod
    def factory(cls, **kwargs) -> "FakeEntryTransport":
        return cls(**kwargs)

    def tls_options(self) -> tuple[bool, bool]:
        return False, True

    async def send_plain(self, to_email: str, subject: str, body: str) -> None:
        await self._record(to_email, subject, body, "plain")

    async def send_html(self, to_email: str, subject: str, body: str) -> None:
        await self._record(to_email, subject, body, "html")

    async def _record(self, to_email: str, subject: str, body: str, subtype: str) -> None:
        self.calls.append((self.host, to_email, subject, subtype))
        error = self.fail_with.get(self.host)
        if error is not None:
            raise error


def smtp_error(code: int, message: str) -> SmtpDeliveryError:
    cause = SMTPResponseException(code, message)
    error = SmtpDeliveryError("SMTPResponseException")
    error.__cause__ = cause
    return error


def make_entry(name: str, **overrides) -> EmailPoolEntry:
    base = {
        "host": f"smtp.{name}.test",
        "from_email": f"noreply@{name}.test",
        "from_name": "AIGC Test",
    }
    base.update(overrides)
    return EmailPoolEntry(name=name, **base)


def make_pool(
    entries: list[EmailPoolEntry], redis_client=None
) -> EmailPoolTransport:
    store = EmailPoolQuotaStore(redis_client, clock=lambda: FIXED_NOW)
    return EmailPoolTransport(entries, quota=store)


class ParseEmailPoolEntriesTests(unittest.TestCase):
    def test_empty_and_whitespace_yield_no_entries(self) -> None:
        self.assertEqual(parse_email_pool_entries(""), [])
        self.assertEqual(parse_email_pool_entries("  \n"), [])

    def test_invalid_json_yields_no_entries(self) -> None:
        self.assertEqual(parse_email_pool_entries("{not json"), [])

    def test_non_list_json_yields_no_entries(self) -> None:
        self.assertEqual(parse_email_pool_entries('{"name":"x"}'), [])

    def test_skips_items_missing_name_or_host(self) -> None:
        entries = parse_email_pool_entries(
            '[{"name":"a"},{"host":"smtp.b.test"},123,'
            '{"name":"ok","host":"smtp.ok.test"}]'
        )
        self.assertEqual([entry.name for entry in entries], ["ok"])

    def test_applies_defaults_and_sorts_by_priority(self) -> None:
        entries = parse_email_pool_entries(
            '[{"name":"b","host":"smtp.b.test","priority":20,"daily_limit":"50"},'
            '{"name":"a","host":"smtp.a.test","priority":10}]',
            default_from_email="noreply@example.test",
            default_from_name="Fallback Name",
        )
        self.assertEqual([entry.name for entry in entries], ["a", "b"])
        first = entries[0]
        self.assertEqual(first.port, 587)
        self.assertEqual(first.from_email, "noreply@example.test")
        self.assertEqual(first.from_name, "Fallback Name")
        self.assertTrue(first.use_tls)
        self.assertEqual(first.daily_limit, 0)
        self.assertEqual(entries[1].daily_limit, 50)

    def test_unparseable_numeric_fields_skip_entry(self) -> None:
        entries = parse_email_pool_entries(
            '[{"name":"bad","host":"smtp.bad.test","port":"not-a-port"}]'
        )
        self.assertEqual(entries, [])


class EmailPoolTransportTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        FakeEntryTransport.reset()
        patcher = patch.object(
            pool_transport, "SmtpTransport", FakeEntryTransport.factory
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    async def test_first_entry_success_records_counters(self) -> None:
        redis = FakeRedis()
        pool = make_pool([make_entry("alpha"), make_entry("beta")], redis)

        await pool.send_plain("user@example.test", "s", "b")

        self.assertEqual(
            FakeEntryTransport.calls,
            [("smtp.alpha.test", "user@example.test", "s", "plain")],
        )
        self.assertEqual(redis.values["email_pool:v1:d:alpha:20260814"], 1)
        self.assertEqual(redis.values["email_pool:v1:m:alpha:202608"], 1)
        self.assertIn("email_pool:v1:d:alpha:20260814", redis.expirations)

    async def test_entry_at_daily_cap_is_skipped(self) -> None:
        redis = FakeRedis()
        redis.values["email_pool:v1:d:alpha:20260814"] = 95
        pool = make_pool(
            [make_entry("alpha", daily_limit=95), make_entry("beta")], redis
        )

        await pool.send_plain("user@example.test", "s", "b")

        self.assertEqual(
            [call[0] for call in FakeEntryTransport.calls], ["smtp.beta.test"]
        )

    async def test_entry_at_monthly_cap_is_skipped(self) -> None:
        redis = FakeRedis()
        redis.values["email_pool:v1:m:alpha:202608"] = 3000
        pool = make_pool(
            [make_entry("alpha", monthly_limit=3000), make_entry("beta")], redis
        )

        await pool.send_plain("user@example.test", "s", "b")

        self.assertEqual(
            [call[0] for call in FakeEntryTransport.calls], ["smtp.beta.test"]
        )

    async def test_quota_error_marks_down_and_fails_over(self) -> None:
        redis = FakeRedis()
        FakeEntryTransport.fail_with["smtp.alpha.test"] = smtp_error(
            452, "too many recipients this hour"
        )
        pool = make_pool([make_entry("alpha"), make_entry("beta")], redis)

        await pool.send_html("user@example.test", "s", "<p>b</p>")

        self.assertEqual(
            [call[0] for call in FakeEntryTransport.calls],
            ["smtp.alpha.test", "smtp.beta.test"],
        )
        down_key = "email_pool:v1:down:alpha:20260814"
        self.assertIn(down_key, redis.values)
        # 12:00 UTC 熔断 → 活到次日零点后 300s 缓冲
        self.assertEqual(redis.expirations[down_key], 43200 + 300)

        FakeEntryTransport.reset()
        await pool.send_plain("user@example.test", "s2", "b2")
        self.assertEqual(
            [call[0] for call in FakeEntryTransport.calls], ["smtp.beta.test"]
        )

    async def test_transient_error_fails_over_without_marking_down(self) -> None:
        redis = FakeRedis()
        FakeEntryTransport.fail_with["smtp.alpha.test"] = smtp_error(
            450, "mailbox busy"
        )
        pool = make_pool([make_entry("alpha"), make_entry("beta")], redis)

        await pool.send_plain("user@example.test", "s", "b")

        self.assertEqual(
            [call[0] for call in FakeEntryTransport.calls],
            ["smtp.alpha.test", "smtp.beta.test"],
        )
        self.assertNotIn("email_pool:v1:down:alpha:20260814", redis.values)

    async def test_all_entries_failing_raises_pool_exhausted(self) -> None:
        redis = FakeRedis()
        FakeEntryTransport.fail_with["smtp.alpha.test"] = smtp_error(450, "busy")
        FakeEntryTransport.fail_with["smtp.beta.test"] = smtp_error(550, "rejected")
        pool = make_pool([make_entry("alpha"), make_entry("beta")], redis)

        with self.assertRaises(SmtpDeliveryError) as ctx:
            await pool.send_plain("user@example.test", "s", "b")
        self.assertEqual(ctx.exception.error_type, "PoolExhausted")

    async def test_unconfigured_entries_are_filtered_out(self) -> None:
        pool = make_pool([EmailPoolEntry(name="ghost", host="")], FakeRedis())
        self.assertFalse(pool.configured)
        with self.assertRaises(SmtpDeliveryError):
            await pool.send_plain("user@example.test", "s", "b")

    async def test_redis_failure_is_fail_open(self) -> None:
        pool = make_pool(
            [make_entry("alpha", daily_limit=1)], ExplodingRedis()
        )
        await pool.send_plain("user@example.test", "s", "b")
        self.assertEqual(
            [call[0] for call in FakeEntryTransport.calls], ["smtp.alpha.test"]
        )

    async def test_none_redis_still_sends(self) -> None:
        pool = make_pool([make_entry("alpha")], None)
        await pool.send_plain("user@example.test", "s", "b")
        self.assertEqual(len(FakeEntryTransport.calls), 1)

    async def test_priority_order_is_respected(self) -> None:
        redis = FakeRedis()
        entries = [
            make_entry("gamma", priority=30),
            make_entry("alpha", priority=10),
            make_entry("beta", priority=20),
        ]
        entries.sort(key=lambda entry: entry.priority)
        pool = make_pool(entries, redis)
        self.assertEqual(pool.host, "smtp.alpha.test")
        self.assertEqual(pool.port, 587)
        self.assertEqual(pool.from_email, "noreply@alpha.test")

    async def test_send_returns_delivering_entry_name(self) -> None:
        pool = make_pool([make_entry("alpha"), make_entry("beta")], FakeRedis())

        provider = await pool.send_plain("user@example.test", "s", "b")

        self.assertEqual(provider, "alpha")

    async def test_send_html_returns_delivering_entry_name(self) -> None:
        pool = make_pool([make_entry("alpha")], FakeRedis())

        provider = await pool.send_html("user@example.test", "s", "<p>b</p>")

        self.assertEqual(provider, "alpha")

    async def test_failover_returns_second_entry_name(self) -> None:
        FakeEntryTransport.fail_with["smtp.alpha.test"] = smtp_error(450, "busy")
        pool = make_pool([make_entry("alpha"), make_entry("beta")], FakeRedis())

        provider = await pool.send_plain("user@example.test", "s", "b")

        self.assertEqual(provider, "beta")
        self.assertTrue(pool.configured)


class IsQuotaErrorTests(unittest.TestCase):
    def test_quota_smtp_codes(self) -> None:
        self.assertTrue(is_quota_error(smtp_error(429, "slow down")))
        self.assertTrue(is_quota_error(smtp_error(452, "over quota")))
        self.assertTrue(is_quota_error(smtp_error(421, "try later")))

    def test_550_only_counts_with_quota_wording(self) -> None:
        self.assertTrue(
            is_quota_error(smtp_error(550, "daily limit exceeded for account"))
        )
        self.assertFalse(is_quota_error(smtp_error(550, "user unknown")))

    def test_transient_codes_are_not_quota(self) -> None:
        self.assertFalse(is_quota_error(smtp_error(450, "mailbox busy")))
        self.assertFalse(is_quota_error(smtp_error(451, "local error")))

    def test_non_response_error_matches_message_hints(self) -> None:
        error = SmtpDeliveryError("SMTPConnectError")
        error.__cause__ = ConnectionError("rate limit hit")
        self.assertTrue(is_quota_error(error))

    def test_no_cause_is_not_quota(self) -> None:
        self.assertFalse(is_quota_error(SmtpDeliveryError("SMTPConnectError")))


class EmailServiceFactoryPoolTests(unittest.TestCase):
    def _make_config(self, pool_json: str, host: str = "smtp.legacy.test"):
        return MagicMock(
            SMTP_HOST=host,
            SMTP_PORT=465,
            SMTP_USERNAME="legacy-user",
            SMTP_PASSWORD="legacy-pass",
            SMTP_FROM_EMAIL="noreply@legacy.test",
            SMTP_FROM_NAME="AIGC Legacy",
            SMTP_USE_TLS=True,
            EMAIL_POOL_JSON=pool_json,
        )

    def test_pool_json_switches_transport_and_appends_legacy(self) -> None:
        service = build_email_service(
            object(),
            config=self._make_config(
                '[{"name":"brevo","host":"smtp-relay.brevo.test","priority":10}]'
            ),
        )
        transport = service._transport
        self.assertIsInstance(transport, EmailPoolTransport)
        names = [entry.name for entry in transport.entries]
        self.assertEqual(names, ["brevo", "legacy-smtp"])
        legacy = transport.entries[-1]
        self.assertEqual(legacy.host, "smtp.legacy.test")
        self.assertEqual(legacy.from_email, "noreply@legacy.test")

    def test_legacy_entry_is_deduped_by_host(self) -> None:
        service = build_email_service(
            object(),
            config=self._make_config(
                '[{"name":"legacy-pooled","host":"smtp.legacy.test"}]'
            ),
        )
        names = [entry.name for entry in service._transport.entries]
        self.assertEqual(names, ["legacy-pooled"])

    def test_invalid_pool_json_falls_back_to_single_smtp(self) -> None:
        service = build_email_service(
            object(), config=self._make_config("{broken")
        )
        self.assertNotIsInstance(service._transport, EmailPoolTransport)
        self.assertEqual(service._transport.host, "smtp.legacy.test")

    def test_config_without_pool_attr_behaves_like_legacy(self) -> None:
        config = MagicMock(
            SMTP_HOST="smtp.legacy.test",
            SMTP_PORT=465,
            SMTP_USERNAME="u",
            SMTP_PASSWORD="p",
            SMTP_FROM_EMAIL="noreply@legacy.test",
            SMTP_FROM_NAME="Legacy",
            SMTP_USE_TLS=True,
        )
        del config.EMAIL_POOL_JSON
        service = build_email_service(object(), config=config)
        self.assertNotIsInstance(service._transport, EmailPoolTransport)


if __name__ == "__main__":
    unittest.main()
