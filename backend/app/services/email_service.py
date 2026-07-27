"""Public facade for email OTP and briefing delivery."""

from __future__ import annotations

import hmac
import logging
import secrets
import string

from fastapi import HTTPException, status

from backend.app.core.config import settings
from backend.app.services.email.message_renderer import EmailMessageRenderer
from backend.app.services.email.otp_store import (
    OtpCooldownError,
    OtpPurpose,
    OtpStoreUnavailableError,
    RedisOtpStore,
)
from backend.app.services.email.smtp_transport import SmtpDeliveryError, SmtpTransport

logger = logging.getLogger(__name__)


def _gen_otp(length: int = 6) -> str:
    """Generate a cryptographically secure numeric OTP."""
    return "".join(secrets.choice(string.digits) for _ in range(length))


class EmailService:
    """Coordinate OTP state, message rendering, and SMTP delivery."""

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

        if not self._transport.configured:
            logger.info(
                "[EMAIL DEV] purpose=%s to=%s otp=%s (SMTP 未配置，跳过真实发送)",
                purpose,
                email_lower,
                otp,
            )
            return

        use_tls, start_tls = self._transport.tls_options()
        logger.info(
            "[EMAIL] 正在发送邮件 to=%s host=%s port=%d use_tls=%s start_tls=%s from=%s",
            email_lower,
            self._transport.host,
            self._transport.port,
            use_tls,
            start_tls,
            self._transport.from_email,
        )
        try:
            await self._transport.send_plain(email_lower, subject, body)
            logger.info("[EMAIL] ✅ 验证码邮件已发送至 %s", email_lower)
        except SmtpDeliveryError as exc:
            cause = exc.__cause__ or exc
            logger.error(
                "[EMAIL] ❌ 发送邮件失败 to=%s  error_type=%s  error=%s",
                email_lower,
                exc.error_type,
                cause,
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"邮件发送失败（{exc.error_type}），请检查 SMTP 配置后重试",
            ) from cause

    async def verify_otp(
        self,
        email: str,
        code: str,
        consume: bool = True,
        *,
        purpose: OtpPurpose = "registration",
    ) -> bool:
        if not self._otp_store.available:
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
        if not self._transport.configured:
            logger.warning(
                "[EMAIL] 简报邮件未发送 to=%s subject=%s (SMTP 未配置)",
                to_email,
                subject,
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="SMTP 未配置，无法发送真实邮件",
            )

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
    otp_store = RedisOtpStore(redis_client, compare_digest=hmac.compare_digest)
    renderer = EmailMessageRenderer()
    transport = SmtpTransport(
        host=config.SMTP_HOST,
        port=config.SMTP_PORT,
        username=config.SMTP_USERNAME,
        password=config.SMTP_PASSWORD,
        from_email=config.SMTP_FROM_EMAIL,
        from_name=config.SMTP_FROM_NAME,
        use_tls=config.SMTP_USE_TLS,
    )
    return EmailService(
        redis_client=redis_client,
        smtp_host=config.SMTP_HOST,
        smtp_port=config.SMTP_PORT,
        smtp_username=config.SMTP_USERNAME,
        smtp_password=config.SMTP_PASSWORD,
        smtp_from_email=config.SMTP_FROM_EMAIL,
        smtp_from_name=config.SMTP_FROM_NAME,
        smtp_use_tls=config.SMTP_USE_TLS,
        otp_store=otp_store,
        renderer=renderer,
        transport=transport,
    )
