from __future__ import annotations

import unittest

from pydantic import ValidationError

from backend.app.api.routes_auth import (
    ChangePasswordRequest,
    RegisterRequest,
    ResetPasswordRequest,
    _validate_new_password,
)


class PasswordPolicyTests(unittest.TestCase):
    """新口令策略：最小长度 8 + 弱口令黑名单 + bcrypt 72 字节上限。

    渗透审计 AUTH-C：原最小 6 位无黑名单，配合登录固定窗口限速
    （每账号 10 次/10 分钟 ≈ 1440 次/天）在线爆破现实可行。
    """

    def test_rejects_short_passwords(self) -> None:
        for value in ("", "a" * 7):
            with self.subTest(value=value), self.assertRaises(ValueError):
                _validate_new_password(value)

    def test_accepts_eight_characters_and_above(self) -> None:
        self.assertEqual(_validate_new_password("x9" * 4), "x9" * 4)

    def test_rejects_blocklisted_passwords_case_insensitively(self) -> None:
        for value in ("1234567890", "ADMIN123456", "Password123", "aigcnews123"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                _validate_new_password(value)

    def test_rejects_over_72_utf8_bytes(self) -> None:
        with self.assertRaises(ValueError):
            _validate_new_password("密" * 25)  # 75 字节
        # 恰好 72 字节放行（bcrypt 截断边界）
        self.assertEqual(_validate_new_password("密" * 24), "密" * 24)

    def test_request_schemas_enforce_policy(self) -> None:
        with self.assertRaises(ValidationError):
            RegisterRequest(
                email="reader@example.com", email_code="123456", password="short"
            )
        with self.assertRaises(ValidationError):
            ResetPasswordRequest(
                email="reader@example.com",
                email_code="123456",
                new_password="admin123456",
            )
        with self.assertRaises(ValidationError):
            ChangePasswordRequest(email_code="123456", new_password="short")
        with self.assertRaises(ValidationError):
            ChangePasswordRequest(email_code="abcde", new_password="x9" * 4)
        # 合法值三个 schema 均放行
        strong = "Str0ng!Passphrase"
        self.assertEqual(
            RegisterRequest(
                email="reader@example.com", email_code="123456", password=strong
            ).password,
            strong,
        )
        self.assertEqual(
            ResetPasswordRequest(
                email="reader@example.com", email_code="123456", new_password=strong
            ).new_password,
            strong,
        )
        self.assertEqual(
            ChangePasswordRequest(email_code="123456", new_password=strong)
            .new_password,
            strong,
        )


if __name__ == "__main__":
    unittest.main()
