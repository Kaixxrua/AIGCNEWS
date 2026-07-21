"""Email OTP 验证码服务（基于 aiosmtplib，结构与 SmsService 平行）。

Dev 模式：SMTP_HOST 为空时，验证码直接打印到日志，不发送真实邮件。
生产模式：通过 aiosmtplib 异步发送 SMTP 邮件。
"""

from __future__ import annotations

import hmac
import logging
import secrets
import string
from typing import Literal

from fastapi import HTTPException, status

logger = logging.getLogger(__name__)

OtpPurpose = Literal["registration", "password_reset"]

_OTP_CODE_PREFIX = "email:code:"
_OTP_LOCK_PREFIX = "email:lock:"
_RESET_CODE_PREFIX = "email:reset:code:"
_RESET_LOCK_PREFIX = "email:reset:lock:"
_RESET_ATTEMPTS_PREFIX = "email:reset:attempts:"
_OTP_TTL = 300  # 验证码有效期 5 分钟
_LOCK_TTL = 60  # 防刷冷却 60 秒
_RESET_MAX_ATTEMPTS = 5


def _gen_otp(length: int = 6) -> str:
    """生成 length 位密码学安全的随机数字 OTP。"""
    return "".join(secrets.choice(string.digits) for _ in range(length))


def _otp_keys(email: str, purpose: OtpPurpose) -> tuple[str, str, str | None]:
    email_lower = email.lower()
    if purpose == "password_reset":
        return (
            f"{_RESET_CODE_PREFIX}{email_lower}",
            f"{_RESET_LOCK_PREFIX}{email_lower}",
            f"{_RESET_ATTEMPTS_PREFIX}{email_lower}",
        )
    return (
        f"{_OTP_CODE_PREFIX}{email_lower}",
        f"{_OTP_LOCK_PREFIX}{email_lower}",
        None,
    )


class EmailService:
    """邮件验证码服务（支持 Redis 防刷 + dev 模式日志输出）。

    Args:
        redis_client: redis.asyncio.Redis 实例。
            如果为 None，表示 Redis 不可用，OTP 功能将降级（仅打印日志，不存储）。
        smtp_host:    SMTP 服务器主机；空字符串表示 dev 模式，仅打印日志。
        smtp_port:    SMTP 端口（默认 587）。
        smtp_username: SMTP 账号。
        smtp_password: SMTP 密码。
        smtp_from_email: 发件人邮箱地址。
        smtp_from_name:  发件人显示名称。
        smtp_use_tls:    是否启用 STARTTLS（默认 True）。
    """

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
    ) -> None:
        self._redis = redis_client
        self._smtp_host = smtp_host
        self._smtp_port = smtp_port
        self._smtp_username = smtp_username
        self._smtp_password = smtp_password
        self._smtp_from_email = smtp_from_email
        self._smtp_from_name = smtp_from_name
        self._smtp_use_tls = smtp_use_tls

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _is_redis_available(self) -> bool:
        return self._redis is not None

    def _is_smtp_configured(self) -> bool:
        return bool(self._smtp_host)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def send_otp(
        self,
        email: str,
        *,
        purpose: OtpPurpose = "registration",
        deliver: bool = True,
    ) -> None:
        """生成并按用途存储邮件 OTP，必要时发送邮件。"""
        email_lower = email.lower()
        code_key, lock_key, attempts_key = _otp_keys(email_lower, purpose)

        if not self._is_redis_available():
            logger.warning("[EMAIL] Redis 不可用，无法生成可验证的 OTP。")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="验证码服务暂不可用，请稍后重试",
            )

        existing_lock = await self._redis.get(lock_key)
        if existing_lock is not None:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="请求过于频繁，请 60 秒后再试",
            )

        otp = _gen_otp()
        await self._redis.set(code_key, otp, ex=_OTP_TTL)
        await self._redis.set(lock_key, "1", ex=_LOCK_TTL)
        if attempts_key is not None:
            await self._redis.delete(attempts_key)

        if not deliver:
            return

        if purpose == "password_reset":
            subject = "【AIGC_NEWS】密码重置验证码"
            body = self._build_password_reset_email_body(otp)
        else:
            subject = "【AIGC_NEWS】您的验证码"
            body = self._build_email_body(otp)

        if self._is_smtp_configured():
            await self._send_email(
                to_email=email_lower,
                subject=subject,
                body=body,
            )
        else:
            # Dev 模式：直接打印到日志，方便本地开发调试
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
        """验证用途隔离的 OTP；Redis 不可用时拒绝验证。"""
        if not self._is_redis_available():
            logger.warning("[EMAIL] Redis 不可用，无法验证 OTP，拒绝请求。")
            return False

        code_key, _lock_key, attempts_key = _otp_keys(email, purpose)
        stored = await self._redis.get(code_key)
        if stored is None:
            return False

        stored_str = stored.decode("utf-8") if isinstance(stored, bytes) else str(stored)
        if hmac.compare_digest(stored_str, code):
            if consume:
                await self.consume_otp(email, purpose=purpose)
            return True

        if attempts_key is not None:
            attempts = await self._redis.incr(attempts_key)
            if attempts == 1:
                await self._redis.expire(attempts_key, _OTP_TTL)
            if attempts >= _RESET_MAX_ATTEMPTS:
                await self._redis.delete(code_key, attempts_key)
        return False

    async def consume_otp(
        self,
        email: str,
        *,
        purpose: OtpPurpose = "registration",
    ) -> None:
        """显式删除 Redis 中的 OTP 状态（在业务流程全部成功后调用）。"""
        if self._is_redis_available():
            code_key, _lock_key, attempts_key = _otp_keys(email, purpose)
            keys = [code_key]
            if attempts_key is not None:
                keys.append(attempts_key)
            await self._redis.delete(*keys)

    # ------------------------------------------------------------------
    # Public: 发送简报邮件
    # ------------------------------------------------------------------

    async def send_briefing(
        self,
        to_email: str,
        briefing_content: str,
        source: str = "all",
        period: str = "daily",
        date_str: str = "",
    ) -> None:
        """将简报内容通过邮件发送给订阅用户。

        Args:
            to_email:  收件人邮箱
            briefing_content: 简报 Markdown 内容
            source:    简报来源类型（all/arxiv/github/...）
            period:    周期（daily/weekly/monthly）
            date_str:  简报日期
        """
        _SOURCE_LABELS = {
            "all": "综合简报",
            "arxiv": "学术报告",
            "github": "工程报告",
            "news": "行业报告",
            "producthunt": "产品报告",
            "hackernews": "社区报告",
        }
        _PERIOD_LABELS = {
            "daily": "日报",
            "weekly": "周报",
            "monthly": "月报",
        }
        source_label = _SOURCE_LABELS.get(source, source)
        period_label = _PERIOD_LABELS.get(period, period)
        subject = f"【AIGC_NEWS】{source_label} · {period_label}"
        if date_str:
            subject += f" ({date_str})"

        # 将 Markdown 简报转换为简单 HTML 邮件
        html_body = self._build_briefing_html(
            briefing_content, source_label, period_label, date_str
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

    # ------------------------------------------------------------------
    # Private: 构建邮件内容
    # ------------------------------------------------------------------

    def _build_email_body(self, otp: str) -> str:
        return (
            f"您好，\n\n"
            f"您正在注册 AIGC_NEWS 账号，验证码为：\n\n"
            f"    {otp}\n\n"
            f"验证码有效期为 5 分钟，请勿泄露给他人。\n\n"
            f"如非本人操作，请忽略此邮件。\n\n"
            f"— AIGC_NEWS"
        )

    def _build_password_reset_email_body(self, otp: str) -> str:
        return (
            f"您好，\n\n"
            f"您正在重置 AIGC_NEWS 账号密码，验证码为：\n\n"
            f"    {otp}\n\n"
            f"验证码有效期为 5 分钟，请勿泄露给他人。\n\n"
            f"如非本人操作，请忽略此邮件，您的密码不会被更改。\n\n"
            f"— AIGC_NEWS"
        )

    def _build_briefing_html(
        self, content: str, source_label: str, period_label: str, date_str: str
    ) -> str:
        """将 Markdown 简报内容包装为 HTML 邮件。"""
        # 简单的 Markdown → HTML 转换（处理标题、粗体、链接、列表）
        import re

        lines = content.split("\n")
        html_lines = []
        for line in lines:
            stripped = line.strip()
            if not stripped:
                html_lines.append("<br/>")
                continue
            # 标题
            if stripped.startswith("### "):
                html_lines.append(
                    f"<h3 style='color:#1a1a2e;margin:16px 0 8px;'>{stripped[4:]}</h3>"
                )
            elif stripped.startswith("## "):
                html_lines.append(
                    f"<h2 style='color:#16213e;margin:20px 0 10px;'>{stripped[3:]}</h2>"
                )
            elif stripped.startswith("# "):
                html_lines.append(
                    f"<h1 style='color:#0f3460;margin:24px 0 12px;'>{stripped[2:]}</h1>"
                )
            elif stripped.startswith("- ") or stripped.startswith("* "):
                html_lines.append(f"<li style='margin:4px 0;'>{stripped[2:]}</li>")
            elif re.match(r"^\d+\.\s", stripped):
                text = re.sub(r"^\d+\.\s*", "", stripped)
                html_lines.append(f"<li style='margin:4px 0;'>{text}</li>")
            elif stripped.startswith("> "):
                html_lines.append(
                    f"<blockquote style='border-left:3px solid #e94560;padding-left:12px;color:#666;margin:8px 0;'>{stripped[2:]}</blockquote>"
                )
            else:
                html_lines.append(
                    f"<p style='margin:6px 0;line-height:1.6;'>{stripped}</p>"
                )

        body_html = "\n".join(html_lines)
        # 处理行内 Markdown：**粗体**、`代码`、[链接](url)
        body_html = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", body_html)
        body_html = re.sub(
            r"`([^`]+)`",
            r'<code style="background:#f0f0f0;padding:2px 4px;border-radius:3px;font-size:0.9em;">\1</code>',
            body_html,
        )
        body_html = re.sub(
            r"\[([^\]]+)\]\(([^)]+)\)",
            r'<a href="\2" style="color:#e94560;">\1</a>',
            body_html,
        )

        return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"/></head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;max-width:680px;margin:0 auto;padding:20px;color:#333;background:#fafafa;">
  <div style="background:linear-gradient(135deg,#0f3460,#16213e);color:white;padding:20px 24px;border-radius:12px 12px 0 0;">
    <h1 style="margin:0;font-size:20px;">📋 AIGC_NEWS · {source_label} · {period_label}</h1>
    <p style="margin:8px 0 0;opacity:0.8;font-size:14px;">{date_str}</p>
  </div>
  <div style="background:white;padding:24px;border-radius:0 0 12px 12px;box-shadow:0 2px 8px rgba(0,0,0,0.08);">
    {body_html}
  </div>
  <div style="text-align:center;padding:16px 0;color:#999;font-size:12px;">
    <p>此邮件由 AIGC_NEWS 自动发送，如需退订请在平台简报中心点击「取消订阅」。</p>
    <p>Powered by AIGC_NEWS</p>
  </div>
</body>
</html>"""

    async def _send_email(self, to_email: str, subject: str, body: str) -> None:
        """通过 aiosmtplib 异步发送邮件。

        端口选择策略：
        - port 465：SSL/TLS 直连（use_tls=True, start_tls=False）— Resend / Gmail SSL
        - port 587：STARTTLS 升级（use_tls=False, start_tls=True）— 通用 SMTP
        - 其他端口：跟随 smtp_use_tls 配置决定使用哪种方式
        """
        import aiosmtplib
        from email.mime.text import MIMEText

        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = subject
        msg["From"] = f"{self._smtp_from_name} <{self._smtp_from_email}>"
        msg["To"] = to_email

        # port 465 = SSL/TLS 直连，port 587 = STARTTLS，其他端口按配置决定
        if self._smtp_port == 465:
            use_tls = True
            start_tls = False
        elif self._smtp_port == 587:
            use_tls = False
            start_tls = True
        else:
            # 自定义端口：smtp_use_tls=True 时默认用 STARTTLS（与旧行为兼容）
            use_tls = False
            start_tls = self._smtp_use_tls

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
            await aiosmtplib.send(
                msg,
                hostname=self._smtp_host,
                port=self._smtp_port,
                username=self._smtp_username or None,
                password=self._smtp_password or None,
                use_tls=use_tls,
                start_tls=start_tls,
            )
            logger.info("[EMAIL] ✅ 验证码邮件已发送至 %s", to_email)
        except Exception as exc:
            # 记录完整错误信息（含类型），便于排查 SMTP 认证/连接问题
            logger.error(
                "[EMAIL] ❌ 发送邮件失败 to=%s  error_type=%s  error=%s",
                to_email,
                type(exc).__name__,
                exc,
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"邮件发送失败（{type(exc).__name__}），请检查 SMTP 配置后重试",
            ) from exc

    async def _send_html_email(
        self, to_email: str, subject: str, html_body: str
    ) -> None:
        """通过 aiosmtplib 异步发送 HTML 邮件（用于简报推送）。"""
        import aiosmtplib
        from email.mime.text import MIMEText

        msg = MIMEText(html_body, "html", "utf-8")
        msg["Subject"] = subject
        msg["From"] = f"{self._smtp_from_name} <{self._smtp_from_email}>"
        msg["To"] = to_email

        if self._smtp_port == 465:
            use_tls = True
            start_tls = False
        elif self._smtp_port == 587:
            use_tls = False
            start_tls = True
        else:
            use_tls = False
            start_tls = self._smtp_use_tls

        logger.info(
            "[EMAIL] 正在发送简报邮件 to=%s subject=%s",
            to_email,
            subject,
        )

        try:
            await aiosmtplib.send(
                msg,
                hostname=self._smtp_host,
                port=self._smtp_port,
                username=self._smtp_username or None,
                password=self._smtp_password or None,
                use_tls=use_tls,
                start_tls=start_tls,
            )
            logger.info("[EMAIL] ✅ 简报邮件已发送至 %s", to_email)
        except Exception as exc:
            logger.error(
                "[EMAIL] ❌ 简报邮件发送失败 to=%s  error_type=%s  error=%s",
                to_email,
                type(exc).__name__,
                exc,
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"简报邮件发送失败（{type(exc).__name__}），请检查 SMTP 配置后重试",
            ) from exc
