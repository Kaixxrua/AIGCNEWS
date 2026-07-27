"""Email OTP, briefing rendering, and SMTP delivery facade."""

from __future__ import annotations

import hmac
import logging
import secrets
import string
from typing import Literal

from fastapi import HTTPException, status

from backend.app.core.config import settings
from backend.app.services.email.message_renderer import EmailMessageRenderer
from backend.app.services.email.otp_store import (
    OtpCooldownError,
    OtpPurpose,
    OtpStoreUnavailableError,
    RedisOtpStore,
    otp_keys,
)
from backend.app.services.email.smtp_transport import SmtpDeliveryError, SmtpTransport

logger = logging.getLogger(__name__)

# Compatibility aliases retained while consumers transition to focused boundaries.
_OTP_TTL = 300
_LOCK_TTL = 60
_RESET_MAX_ATTEMPTS = 5


def _gen_otp(length: int = 6) -> str:
    """Generate a cryptographically secure numeric OTP."""
    return "".join(secrets.choice(string.digits) for _ in range(length))


def _otp_keys(email: str, purpose: OtpPurpose) -> tuple[str, str, str | None]:
    return otp_keys(email, purpose)


class EmailService:
    """Public email facade preserving the legacy constructor and async API."""

    def __init__(
        self,
        redis_client,
        smtp_host: str = "",
        smtp_port: int = 587,
        smtp_username: str = "",
        smtp_password: str = "",
        smtp_from_email: str = "no-reply@example.com",
        smtp_from_name: str = "AIGC_NEWS",
        smtp_use_tls: bool = True,
        *,
        otp_store: RedisOtpStore | None = None,
        renderer: EmailMessageRenderer | None = None,
        transport: SmtpTransport | None = None,
    ) -> None:
        self._redis = redis_client
        self._smtp_host = smtp_host
        self._smtp_port = smtp_port
        self._smtp_username = smtp_username
        self._smtp_password = smtp_password
        self._smtp_from_email = smtp_from_email
        self._smtp_from_name = smtp_from_name
        self._smtp_use_tls = smtp_use_tls
        self._otp_store = otp_store or RedisOtpStore(
            redis_client, compare_digest=hmac.compare_digest
        )
        self._renderer = renderer or EmailMessageRenderer()
        self._transport = transport or SmtpTransport(
            host=smtp_host,
            port=smtp_port,
            username=smtp_username,
            password=smtp_password,
            from_email=smtp_from_email,
            from_name=smtp_from_name,
            use_tls=smtp_use_tls,
        )

    def _is_redis_available(self) -> bool:
        return self._otp_store.available

    def _is_smtp_configured(self) -> bool:
        return self._transport.configured

    async def send_otp(
        self,
        email: str,
        *,
        purpose: OtpPurpose = "registration",
        deliver: bool = True,
    ) -> None:
        email_lower = email.lower()
        otp = _gen_otp()
        try:
            await self._otp_store.store(email_lower, otp, purpose=purpose)
        except OtpStoreUnavailableError as exc:
            logger.warning("[EMAIL] Redis 不可用，无法生成可验证的 OTP。")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="验证码服务暂不可用，请稍后重试",
            ) from exc
        except OtpCooldownError as exc:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="请求过于频繁，请 60 秒后再试",
            ) from exc

        if not deliver:
            return

        if purpose == "password_reset":
            subject, body = self._renderer.password_reset_otp(otp)
        else:
            subject, body = self._renderer.registration_otp(otp)

        if self._is_smtp_configured():
            await self._send_email(to_email=email_lower, subject=subject, body=body)
        else:
            logger.info(
                "[EMAIL DEV] purpose=%s to=%s otp=%s (SMTP 未配置，跳过真实发送)",
                purpose,
                email_lower,
                otp,
            )

    async def verify_otp(
        self,
        email: str,
        code: str,
        consume: bool = True,
        *,
        purpose: OtpPurpose = "registration",
    ) -> bool:
        if not self._is_redis_available():
            logger.warning("[EMAIL] Redis 不可用，无法验证 OTP，拒绝请求。")
            return False
        return await self._otp_store.verify(
            email,
            code,
            purpose=purpose,
            consume=consume,
        )

    async def consume_otp(
        self,
        email: str,
        *,
        purpose: OtpPurpose = "registration",
    ) -> None:
        await self._otp_store.consume(email, purpose=purpose)

    async def send_briefing(
        self,
        to_email: str,
        briefing_content: str,
        source: str = "all",
        period: str = "daily",
        date_str: str = "",
    ) -> None:
        subject, html_body = self._renderer.briefing(
            briefing_content, source, period, date_str
        )
        if self._is_smtp_configured():
            await self._send_html_email(
                to_email=to_email, subject=subject, html_body=html_body
            )
        else:
            logger.warning(
                "[EMAIL] 简报邮件未发送 to=%s subject=%s (SMTP 未配置)",
                to_email,
                subject,
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="SMTP 未配置，无法发送真实邮件",
            )

    # Compatibility delegates retained for existing tests and private callers.
    def _build_email_body(self, otp: str) -> str:
        return self._renderer.registration_otp_body(otp)

    def _build_password_reset_email_body(self, otp: str) -> str:
        return self._renderer.password_reset_otp_body(otp)

    def _build_briefing_html(
        self, content: str, source_label: str, period_label: str, date_str: str
    ) -> str:
        return self._renderer.briefing_html(
            content, source_label, period_label, date_str
        )

    async def _send_email(self, to_email: str, subject: str, body: str) -> None:
        use_tls, start_tls = self._transport.tls_options()
        logger.info(
            "[EMAIL] 正在发送邮件 to=%s host=%s port=%d use_tls=%s start_tls=%s from=%s",
            to_email,
            self._smtp_host,
            self._smtp_port,
            use_tls,
            start_tls,
            self._smtp_from_email,
        )
        try:
            await self._transport.send_plain(to_email, subject, body)
            logger.info("[EMAIL] ✅ 验证码邮件已发送至 %s", to_email)
        except SmtpDeliveryError as exc:
            cause = exc.__cause__ or exc
            logger.error(
                "[EMAIL] ❌ 发送邮件失败 to=%s  error_type=%s  error=%s",
                to_email,
                exc.error_type,
                cause,
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"邮件发送失败（{exc.error_type}），请检查 SMTP 配置后重试",
            ) from cause

    async def _send_html_email(
        self, to_email: str, subject: str, html_body: str
    ) -> None:
        logger.info("[EMAIL] 正在发送简报邮件 to=%s subject=%s", to_email, subject)
        try:
            await self._transport.send_html(to_email, subject, html_body)
            logger.info("[EMAIL] ✅ 简报邮件已发送至 %s", to_email)
        except SmtpDeliveryError as exc:
            cause = exc.__cause__ or exc
            logger.error(
                "[EMAIL] ❌ 简报邮件发送失败 to=%s  error_type=%s  error=%s",
                to_email,
                exc.error_type,
                cause,
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"简报邮件发送失败（{exc.error_type}），请检查 SMTP 配置后重试",
            ) from cause


def build_email_service(redis_client, *, config=settings) -> EmailService:
    """Build an email service from application SMTP settings."""
    return EmailService(
        redis_client=redis_client,
        smtp_host=config.SMTP_HOST,
        smtp_port=config.SMTP_PORT,
        smtp_username=config.SMTP_USERNAME,
        smtp_password=config.SMTP_PASSWORD,
        smtp_from_email=config.SMTP_FROM_EMAIL,
        smtp_from_name=config.SMTP_FROM_NAME,
        smtp_use_tls=config.SMTP_USE_TLS,
    )
