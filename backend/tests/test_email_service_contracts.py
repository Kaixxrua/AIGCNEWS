from __future__ import annotations

import unittest
from email import message_from_bytes
from email.header import decode_header, make_header
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from backend.app.services import email_service
from backend.app.services.email.message_renderer import EmailMessageRenderer
from backend.app.services.email.otp_store import RedisOtpStore
from backend.app.services.email.smtp_transport import SmtpDeliveryError, SmtpTransport
from backend.app.services.email_service import (
    BriefingDeliveryError,
    EmailService,
    OtpDeliveryUnavailableError,
    OtpSendRateLimitedError,
    build_email_service,
)


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, object] = {}
        self.expirations: dict[str, int] = {}
        self.calls: list[tuple[object, ...]] = []

    async def get(self, key: str):
        self.calls.append(("get", key))
        return self.values.get(key)

    async def set(self, key: str, value: object, *, ex: int | None = None):
        self.calls.append(("set", key, value, ex))
        self.values[key] = value
        if ex is not None:
            self.expirations[key] = ex

    async def delete(self, *keys: str):
        self.calls.append(("delete", *keys))
        for key in keys:
            self.values.pop(key, None)
            self.expirations.pop(key, None)

    async def incr(self, key: str) -> int:
        self.calls.append(("incr", key))
        value = int(self.values.get(key, 0)) + 1
        self.values[key] = value
        return value

    async def expire(self, key: str, seconds: int):
        self.calls.append(("expire", key, seconds))
        self.expirations[key] = seconds


class EmailOtpContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_registration_uses_lowercase_keys_ttls_and_non_atomic_sequence(self) -> None:
        redis = FakeRedis()
        service = EmailService(redis)

        with patch("backend.app.services.email_service._gen_otp", return_value="123456"):
            await service.send_otp("User@Example.COM", deliver=False)

        self.assertEqual(
            redis.calls,
            [
                ("get", "email:lock:user@example.com"),
                ("set", "email:code:user@example.com", "123456", 300),
                ("set", "email:lock:user@example.com", "1", 60),
                ("delete", "email:attempts:user@example.com"),
            ],
        )

    async def test_password_reset_uses_isolated_keys_and_resets_attempts(self) -> None:
        redis = FakeRedis()
        redis.values["email:reset:attempts:user@example.com"] = 3
        service = EmailService(redis)

        with patch("backend.app.services.email_service._gen_otp", return_value="654321"):
            await service.send_otp(
                "User@Example.COM", purpose="password_reset", deliver=False
            )

        self.assertEqual(
            redis.calls,
            [
                ("get", "email:reset:lock:user@example.com"),
                ("set", "email:reset:code:user@example.com", "654321", 300),
                ("set", "email:reset:lock:user@example.com", "1", 60),
                ("delete", "email:reset:attempts:user@example.com"),
            ],
        )

    async def test_cooldown_rejects_before_code_write(self) -> None:
        redis = FakeRedis()
        redis.values["email:lock:user@example.com"] = b"1"
        service = EmailService(redis)

        with self.assertRaises(OtpSendRateLimitedError) as context:
            await service.send_otp("USER@example.com", deliver=False)

        self.assertEqual(context.exception.detail, "请求过于频繁，请 60 秒后再试")
        self.assertEqual(redis.calls, [("get", "email:lock:user@example.com")])

    async def test_unavailable_redis_preserves_send_and_verify_divergence(self) -> None:
        service = EmailService(None)

        with self.assertRaises(OtpDeliveryUnavailableError) as context:
            await service.send_otp("user@example.com", deliver=False)

        self.assertEqual(context.exception.detail, "验证码服务暂不可用，请稍后重试")
        self.assertFalse(await service.verify_otp("user@example.com", "123456"))

    async def test_deliver_false_still_writes_otp_without_smtp(self) -> None:
        redis = FakeRedis()
        service = EmailService(redis, smtp_host="smtp.example.test")

        with (
            patch("backend.app.services.email_service._gen_otp", return_value="123456"),
            patch("aiosmtplib.send", new_callable=AsyncMock) as send,
        ):
            await service.send_otp("user@example.com", deliver=False)

        self.assertEqual(redis.values["email:code:user@example.com"], "123456")
        send.assert_not_awaited()

    async def test_verify_consume_false_and_default_single_use(self) -> None:
        redis = FakeRedis()
        redis.values["email:code:user@example.com"] = b"123456"
        service = EmailService(redis)

        self.assertTrue(await service.verify_otp("USER@example.com", "123456", False))
        self.assertIn("email:code:user@example.com", redis.values)
        self.assertTrue(await service.verify_otp("user@example.com", "123456"))
        self.assertNotIn("email:code:user@example.com", redis.values)

    async def test_reset_failures_expire_attempts_then_delete_at_five(self) -> None:
        redis = FakeRedis()
        redis.values["email:reset:code:user@example.com"] = "654321"
        service = EmailService(redis)

        for _ in range(5):
            self.assertFalse(
                await service.verify_otp(
                    "USER@example.com", "000000", purpose="password_reset"
                )
            )

        self.assertIn(("expire", "email:reset:attempts:user@example.com", 300), redis.calls)
        self.assertEqual(redis.calls.count(("expire", "email:reset:attempts:user@example.com", 300)), 1)
        self.assertEqual(
            redis.calls[-1],
            (
                "delete",
                "email:reset:code:user@example.com",
                "email:reset:attempts:user@example.com",
            ),
        )

    async def test_consume_reset_deletes_code_and_attempts_but_not_lock(self) -> None:
        redis = FakeRedis()
        redis.values.update(
            {
                "email:reset:code:user@example.com": "123456",
                "email:reset:attempts:user@example.com": 2,
                "email:reset:lock:user@example.com": "1",
            }
        )
        service = EmailService(redis)

        await service.consume_otp("USER@example.com", purpose="password_reset")

        self.assertEqual(
            redis.calls,
            [
                (
                    "delete",
                    "email:reset:code:user@example.com",
                    "email:reset:attempts:user@example.com",
                )
            ],
        )
        self.assertIn("email:reset:lock:user@example.com", redis.values)


class EmailRenderingContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.renderer = EmailMessageRenderer()

    def test_otp_plain_text_bodies_are_exact(self) -> None:
        self.assertEqual(
            self.renderer.registration_otp_body("123456"),
            "您好，\n\n您正在注册 AIGC_NEWS 账号，验证码为：\n\n"
            "    123456\n\n验证码有效期为 5 分钟，请勿泄露给他人。\n\n"
            "如非本人操作，请忽略此邮件。\n\n— AIGC_NEWS",
        )
        self.assertEqual(
            self.renderer.password_reset_otp_body("654321"),
            "您好，\n\n您正在重置 AIGC_NEWS 账号密码，验证码为：\n\n"
            "    654321\n\n验证码有效期为 5 分钟，请勿泄露给他人。\n\n"
            "如非本人操作，请忽略此邮件，您的密码不会被更改。\n\n— AIGC_NEWS",
        )

    def test_briefing_html_and_unescaped_content_are_exact(self) -> None:
        content = "# <Title>\n## Section\n### Detail\n- **bold**\n1. `code`\n> quote\n[link](https://example.test/?a=1&b=2)\n"
        html = self.renderer.briefing_html(
            content, "综合简报", "日报", "2026-07-27"
        )

        self.assertEqual(
            html,
            """<!DOCTYPE html>
<html>
<head><meta charset="utf-8"/></head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;max-width:680px;margin:0 auto;padding:20px;color:#333;background:#fafafa;">
  <div style="background:linear-gradient(135deg,#0f3460,#16213e);color:white;padding:20px 24px;border-radius:12px 12px 0 0;">
    <h1 style="margin:0;font-size:20px;">📋 AIGC_NEWS · 综合简报 · 日报</h1>
    <p style="margin:8px 0 0;opacity:0.8;font-size:14px;">2026-07-27</p>
  </div>
  <div style="background:white;padding:24px;border-radius:0 0 12px 12px;box-shadow:0 2px 8px rgba(0,0,0,0.08);">
    <h1 style='color:#0f3460;margin:24px 0 12px;'><Title></h1>
<h2 style='color:#16213e;margin:20px 0 10px;'>Section</h2>
<h3 style='color:#1a1a2e;margin:16px 0 8px;'>Detail</h3>
<li style='margin:4px 0;'><strong>bold</strong></li>
<li style='margin:4px 0;'><code style="background:#f0f0f0;padding:2px 4px;border-radius:3px;font-size:0.9em;">code</code></li>
<blockquote style='border-left:3px solid #e94560;padding-left:12px;color:#666;margin:8px 0;'>quote</blockquote>
<p style='margin:6px 0;line-height:1.6;'><a href="https://example.test/?a=1&b=2" style="color:#e94560;">link</a></p>
<br/>
  </div>
  <div style="text-align:center;padding:16px 0;color:#999;font-size:12px;">
    <p>此邮件由 AIGC_NEWS 自动发送，如需退订请在平台简报中心点击「取消订阅」。</p>
    <p>Powered by AIGC_NEWS</p>
  </div>
</body>
</html>""",
        )


class EmailDeliveryContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_otp_dev_mode_logs_success_after_storage(self) -> None:
        redis = FakeRedis()
        service = EmailService(redis)

        with (
            patch("backend.app.services.email_service._gen_otp", return_value="123456"),
            patch.object(email_service.settings, "env", "development"),
            self.assertLogs("backend.app.services.email_service", level="INFO") as logs,
        ):
            await service.send_otp("USER@example.com")

        self.assertIn(
            "[EMAIL DEV] purpose=registration to=user@example.com otp=123456 (SMTP 未配置，跳过真实发送)",
            "\n".join(logs.output),
        )

    async def test_otp_unconfigured_smtp_outside_development_is_refused(self) -> None:
        redis = FakeRedis()
        service = EmailService(redis)

        with (
            patch("backend.app.services.email_service._gen_otp", return_value="123456"),
            patch.object(email_service.settings, "env", "production"),
            self.assertLogs("backend.app.services.email_service", level="ERROR") as logs,
        ):
            with self.assertRaises(OtpDeliveryUnavailableError) as context:
                await service.send_otp("USER@example.com")

        self.assertEqual(context.exception.detail, "邮件服务暂不可用，请稍后重试")
        output = "\n".join(logs.output)
        self.assertIn("SMTP 未配置", output)
        # 任何分支都不得把明文验证码写进日志
        self.assertNotIn("123456", output)
        self.assertNotIn("[EMAIL DEV]", output)
        # 验证码已落库但拒绝投递：占用冷却与尝试策略，行为同 SMTP 发送失败路径
        self.assertEqual(redis.values["email:code:user@example.com"], "123456")

    def test_development_env_detection_matches_main_reload_policy(self) -> None:
        for env, expected in (
            ("development", True),
            ("dev", True),
            ("DEVELOPMENT", True),
            ("production", False),
            ("staging", False),
            ("", False),
        ):
            with self.subTest(env=env):
                with patch.object(email_service.settings, "env", env):
                    self.assertIs(email_service._is_development_env(), expected)

    async def test_briefing_dev_mode_raises_delivery_error_with_exact_detail(self) -> None:
        service = EmailService(None)

        with self.assertRaises(BriefingDeliveryError) as context:
            await service.send_briefing("reader@example.com", "content")

        self.assertEqual(context.exception.detail, "SMTP 未配置，无法发送真实邮件")

    async def test_send_otp_preserves_subject_plain_mime_and_lowercase_recipient(self) -> None:
        redis = FakeRedis()
        service = EmailService(
            redis,
            smtp_host="smtp.example.test",
            smtp_port=587,
            smtp_from_email="sender@example.test",
            smtp_from_name="AIGC Test",
        )

        with (
            patch("backend.app.services.email_service._gen_otp", return_value="123456"),
            patch("aiosmtplib.send", new_callable=AsyncMock) as send,
        ):
            await service.send_otp("USER@example.com")

        message = send.await_args.args[0]
        parsed = message_from_bytes(message.as_bytes())
        self.assertEqual(str(make_header(decode_header(parsed["Subject"]))), "【AIGC_NEWS】您的验证码")
        self.assertEqual(parsed["From"], "AIGC Test <sender@example.test>")
        self.assertEqual(parsed["To"], "user@example.com")
        self.assertEqual(parsed.get_content_type(), "text/plain")
        self.assertEqual(parsed.get_content_charset(), "utf-8")
        self.assertIn("    123456", parsed.get_payload(decode=True).decode("utf-8"))

    async def test_briefing_subject_html_mime_and_labels_are_preserved(self) -> None:
        service = EmailService(
            None,
            smtp_host="smtp.example.test",
            smtp_from_email="sender@example.test",
            smtp_from_name="AIGC Test",
        )

        with patch("aiosmtplib.send", new_callable=AsyncMock) as send:
            await service.send_briefing(
                "Reader@Example.COM",
                "content",
                source="github",
                period="daily",
                date_str="2026-07-27",
            )

        parsed = message_from_bytes(send.await_args.args[0].as_bytes())
        self.assertEqual(
            str(make_header(decode_header(parsed["Subject"]))), "【AIGC_NEWS】工程报告 · 日报 (2026-07-27)"
        )
        self.assertEqual(parsed["To"], "Reader@Example.COM")
        self.assertEqual(parsed.get_content_type(), "text/html")
        self.assertIn(
            "AIGC_NEWS · 工程报告 · 日报",
            parsed.get_payload(decode=True).decode("utf-8"),
        )

    async def test_tls_port_matrix_and_empty_credentials(self) -> None:
        cases = [
            (465, False, True, False),
            (587, False, False, True),
            (2525, True, False, True),
            (2525, False, False, False),
        ]
        for port, configured_tls, use_tls, start_tls in cases:
            with self.subTest(port=port, configured_tls=configured_tls):
                service = EmailService(
                    None,
                    smtp_host="smtp.example.test",
                    smtp_port=port,
                    smtp_use_tls=configured_tls,
                )
                with patch("aiosmtplib.send", new_callable=AsyncMock) as send:
                    await service._transport.send_plain(
                        "to@example.test", "subject", "body"
                    )
                self.assertEqual(
                    send.await_args.kwargs,
                    {
                        "hostname": "smtp.example.test",
                        "port": port,
                        "username": None,
                        "password": None,
                        "use_tls": use_tls,
                        "start_tls": start_tls,
                    },
                )

    async def test_plain_and_html_smtp_errors_keep_distinct_details(self) -> None:
        redis = FakeRedis()
        service = EmailService(redis, smtp_host="smtp.example.test")
        with (
            patch("backend.app.services.email_service._gen_otp", return_value="123456"),
            patch(
                "aiosmtplib.send",
                new_callable=AsyncMock,
                side_effect=TimeoutError("boom"),
            ),
        ):
            with self.assertRaises(OtpDeliveryUnavailableError) as plain_context:
                await service.send_otp("to@example.test")
            redis.values.pop("email:lock:to@example.test")
            with self.assertRaises(BriefingDeliveryError) as html_context:
                await service.send_briefing("to@example.test", "content")

        self.assertEqual(
            plain_context.exception.detail,
            "邮件发送失败（TimeoutError），请检查 SMTP 配置后重试",
        )
        self.assertEqual(
            html_context.exception.detail,
            "简报邮件发送失败（TimeoutError），请检查 SMTP 配置后重试",
        )


class ExtractedEmailBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_otp_store_matches_legacy_sequence_and_attempt_policy(self) -> None:
        redis = FakeRedis()
        store = RedisOtpStore(redis)

        await store.store("USER@example.com", "123456", purpose="password_reset")
        for _ in range(5):
            self.assertFalse(
                await store.verify(
                    "USER@example.com",
                    "000000",
                    purpose="password_reset",
                    consume=True,
                )
            )

        self.assertEqual(
            redis.calls[:4],
            [
                ("get", "email:reset:lock:user@example.com"),
                ("set", "email:reset:code:user@example.com", "123456", 300),
                ("set", "email:reset:lock:user@example.com", "1", 60),
                ("delete", "email:reset:attempts:user@example.com"),
            ],
        )
        self.assertEqual(
            redis.calls[-1],
            (
                "delete",
                "email:reset:code:user@example.com",
                "email:reset:attempts:user@example.com",
            ),
        )

    async def test_registration_otp_enforces_max_attempts_like_password_reset(self) -> None:
        redis = FakeRedis()
        store = RedisOtpStore(redis)

        await store.store("USER@example.com", "123456", purpose="registration")
        for _ in range(5):
            self.assertFalse(
                await store.verify(
                    "USER@example.com",
                    "000000",
                    purpose="registration",
                    consume=True,
                )
            )

        # 第 5 次错误尝试后验证码即被销毁，即使输入正确也无法通过
        self.assertNotIn("email:code:user@example.com", redis.values)
        self.assertFalse(
            await store.verify(
                "USER@example.com",
                "123456",
                purpose="registration",
                consume=True,
            )
        )

    async def test_smtp_transport_preserves_mime_tls_credentials_and_error_type(self) -> None:
        transport = SmtpTransport(
            host="smtp.example.test",
            port=465,
            username="",
            password="",
            from_email="sender@example.test",
            from_name="AIGC Test",
            use_tls=False,
        )

        with patch("aiosmtplib.send", new_callable=AsyncMock) as send:
            await transport.send_html("to@example.test", "subject", "<p>body</p>")

        message = send.await_args.args[0]
        self.assertEqual(message.get_content_type(), "text/html")
        self.assertEqual(
            send.await_args.kwargs,
            {
                "hostname": "smtp.example.test",
                "port": 465,
                "username": None,
                "password": None,
                "use_tls": True,
                "start_tls": False,
            },
        )

        with patch(
            "aiosmtplib.send", new_callable=AsyncMock, side_effect=TimeoutError("boom")
        ):
            with self.assertRaises(SmtpDeliveryError) as context:
                await transport.send_plain("to@example.test", "subject", "body")
        self.assertEqual(context.exception.error_type, "TimeoutError")
        self.assertIsInstance(context.exception.__cause__, TimeoutError)


class EmailFactoryContractTests(unittest.TestCase):
    def test_factory_signature_and_mapping_are_preserved(self) -> None:
        redis = object()
        config = SimpleNamespace(
            SMTP_HOST="smtp.example.test",
            SMTP_PORT=2465,
            SMTP_USERNAME="user",
            SMTP_PASSWORD="password",
            SMTP_FROM_EMAIL="sender@example.test",
            SMTP_FROM_NAME="AIGC Test",
            SMTP_USE_TLS=False,
        )

        service = build_email_service(redis, config=config)

        self.assertIsInstance(service, EmailService)
        self.assertIs(service._otp_store._redis, redis)
        self.assertEqual(service._transport.host, "smtp.example.test")
        self.assertEqual(service._transport.port, 2465)
        self.assertEqual(service._transport._username, "user")
        self.assertEqual(service._transport._password, "password")
        self.assertEqual(service._transport.from_email, "sender@example.test")
        self.assertEqual(service._transport._from_name, "AIGC Test")
        self.assertFalse(service._transport._use_tls)


if __name__ == "__main__":
    unittest.main()
