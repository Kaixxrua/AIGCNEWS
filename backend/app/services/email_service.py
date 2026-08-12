"""Public facade for email OTP and briefing delivery."""

from __future__ import annotations

import hmac
import logging
import secrets
import string

from backend.app.core.config import settings
from backend.app.services.email.message_renderer import EmailMessageRenderer
from backend.app.services.email.otp_store import (
    OtpCooldownError,
    OtpPurpose,
    OtpStoreUnavailableError,
    RedisOtpStore,
)
from backend.app.services.email.smtp_config_provider import resolve_smtp_config
from backend.app.services.email.smtp_transport import SmtpDeliveryError, SmtpTransport

logger = logging.getLogger(__name__)


class EmailServiceError(Exception):
    """邮件服务领域错误基类。

    detail 为可安全回显给客户端的文案；HTTP 状态码由路由层映射，
    服务层不感知传输协议。
    """

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class OtpDeliveryUnavailableError(EmailServiceError):
    """验证码存储或投递通道不可用（路由层映射 503）。"""


class OtpSendRateLimitedError(EmailServiceError):
    """OTP 发送冷却期命中（路由层映射 429）。"""


class BriefingDeliveryError(EmailServiceError):
    """简报邮件投递失败（路由层映射 503）。"""


def _gen_otp(length: int = 6) -> str:
    """Generate a cryptographically secure numeric OTP."""
    return "".join(secrets.choice(string.digits) for _ in range(length))


def _is_development_env() -> bool:
    """开发环境判定与 main.py 热重载口径一致：ENV=development/dev。"""
    return settings.env.lower() in ("development", "dev")


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
            raise OtpDeliveryUnavailableError("验证码服务暂不可用，请稍后重试") from exc
        except OtpCooldownError as exc:
            raise OtpSendRateLimitedError("请求过于频繁，请 60 秒后再试") from exc

        if not deliver:
            return

        if purpose == "password_reset":
            subject, body = self._renderer.password_reset_otp(otp)
        elif purpose == "push_channel_verify":
            subject, body = self._renderer.channel_binding_otp(otp)
        else:
            subject, body = self._renderer.registration_otp(otp)

        if not self._transport.configured:
            if _is_development_env():
                logger.info(
                    "[EMAIL DEV] purpose=%s to=%s otp=%s (SMTP 未配置，跳过真实发送)",
                    purpose,
                    email_lower,
                    otp,
                )
                return
            # 非开发环境 SMTP 未配置：明文验证码进日志即泄露，拒绝发码；
            # 路由层统一映射 503，行为与 SMTP 发送失败路径一致
            logger.error(
                "[EMAIL] SMTP 未配置且非开发环境，拒绝发放验证码 purpose=%s to=%s",
                purpose,
                email_lower,
            )
            raise OtpDeliveryUnavailableError("邮件服务暂不可用，请稍后重试")

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
            raise OtpDeliveryUnavailableError(
                f"邮件发送失败（{exc.error_type}），请检查 SMTP 配置后重试"
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
            raise BriefingDeliveryError("SMTP 未配置，无法发送真实邮件")

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
            raise BriefingDeliveryError(
                f"简报邮件发送失败（{exc.error_type}），请检查 SMTP 配置后重试"
            ) from cause


def build_email_service(redis_client, *, config=None) -> EmailService:
    """Build an email service from application SMTP settings.

    config 为 None（生产默认）时经 smtp_config_provider 解析生效配置
    （DB 行覆盖 env，60s TTL 热生效）；显式传入 Settings 兼容对象则
    保持旧的属性读取路径（测试与独立脚本专用）。
    """
    if config is None:
        resolved = resolve_smtp_config(env=settings)
        host = resolved.host
        port = resolved.port
        username = resolved.username
        password = resolved.password
        from_email = resolved.from_email
        from_name = resolved.from_name
        use_tls = resolved.use_tls
    else:
        host = config.SMTP_HOST
        port = config.SMTP_PORT
        username = config.SMTP_USERNAME
        password = config.SMTP_PASSWORD
        from_email = config.SMTP_FROM_EMAIL
        from_name = config.SMTP_FROM_NAME
        use_tls = config.SMTP_USE_TLS
    otp_store = RedisOtpStore(redis_client, compare_digest=hmac.compare_digest)
    renderer = EmailMessageRenderer()
    transport = SmtpTransport(
        host=host,
        port=port,
        username=username,
        password=password,
        from_email=from_email,
        from_name=from_name,
        use_tls=use_tls,
    )
    return EmailService(
        redis_client=redis_client,
        smtp_host=host,
        smtp_port=port,
        smtp_username=username,
        smtp_password=password,
        smtp_from_email=from_email,
        smtp_from_name=from_name,
        smtp_use_tls=use_tls,
        otp_store=otp_store,
        renderer=renderer,
        transport=transport,
    )
