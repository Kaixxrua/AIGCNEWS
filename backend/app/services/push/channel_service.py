"""推送渠道的领域编排：创建（含验证码签发）、校验、停用与测试投递。"""

from __future__ import annotations

import asyncio
from typing import Any

from backend.app.repositories.push_channel_repository import PushChannelRepository
from backend.app.services.email_service import EmailService
from backend.app.services.membership.tiers import (
    MEMBERSHIP_TIER_MEMBER,
    resolve_effective_tier,
)
from backend.app.services.push.errors import (
    InvalidChannelOtpError,
    PushChannelDisabledError,
    PushChannelDuplicateError,
    PushChannelNotFoundError,
    PushChannelNotVerifiedError,
    TelegramNotConfiguredError,
    VipRequiredError,
    WebhookProbeFailedError,
)
from backend.app.services.push.secrets import seal_channel_config, unseal_channel_config
from backend.app.services.push.webhook_service import (
    WebhookSender,
    validate_webhook_url,
)

CHANNEL_TYPE_EMAIL = "email"
CHANNEL_TYPE_WEBHOOK = "webhook"
CHANNEL_TYPE_DISCORD = "discord"
CHANNEL_TYPE_TELEGRAM = "telegram"
CHANNEL_STATUS_ACTIVE = "active"
CHANNEL_STATUS_DISABLED = "disabled"
CHANNEL_OTP_PURPOSE = "push_channel_verify"

_TEST_BRIEFING_CONTENT = """# AIGC Radar 推送渠道测试

这是一封渠道验证邮件：你的邮件推送渠道已配置成功。

订阅生效后，你将按设定的频率收到对应来源的 AI 垂直简报。

— AIGC Radar · aigcnews.cn
"""

_TEST_WEBHOOK_TITLE = "AIGC Radar 推送渠道测试"
_TEST_WEBHOOK_CONTENT = (
    "这是一条渠道验证消息：你的 Webhook 推送渠道已配置成功。\n\n"
    "订阅生效后，你将按设定的频率收到对应来源的 AI 垂直简报。\n\n"
    "— AIGC Radar · aigcnews.cn"
)

_PROBE_WEBHOOK_TITLE = "AIGC Radar 渠道绑定验证"
_PROBE_WEBHOOK_CONTENT = (
    "你的 Webhook 推送渠道绑定成功。\n\n"
    "回到 aigcnews.cn 为订阅选择该渠道后，即可按频率接收 AI 垂直简报。"
)


class PushChannelService:
    """用户推送渠道的领域服务。

    同步仓储调用一律经 ``asyncio.to_thread`` 转移（对齐 account_lifecycle
    的并发约定），邮件投递为原生异步。
    """

    def __init__(self, channels: PushChannelRepository) -> None:
        self._channels = channels

    @staticmethod
    def require_direct_channel_entitlement(user: dict[str, Any]) -> None:
        """Require an effective member tier for bot/webhook channels."""
        if user.get("role") == "admin":
            return
        tier = resolve_effective_tier(
            user.get("membership_tier"), user.get("membership_expires_at")
        )
        if tier != MEMBERSHIP_TIER_MEMBER:
            raise VipRequiredError("当前功能仅对有效会员开放")

    async def create_email_channel(
        self,
        *,
        user_id: int,
        email: str,
        email_service: EmailService,
    ) -> tuple[dict[str, Any], bool]:
        """创建 email 渠道并签发绑定验证码。

        返回 (channel, created)。同一邮箱重复绑定时：已验证 → 409 领域错误；
        未验证 → 重发验证码并返回既有渠道（created=False），避免重复行。
        """
        target = email.strip().lower()
        existing = await asyncio.to_thread(
            self._channels.find_channel_by_target,
            user_id=user_id,
            channel_type=CHANNEL_TYPE_EMAIL,
            target=target,
        )
        if existing is not None and existing["verified"]:
            raise PushChannelDuplicateError("该邮箱已绑定推送渠道")
        channel = existing
        created = False
        if channel is None:
            channel = await asyncio.to_thread(
                self._channels.create_channel,
                user_id=user_id,
                channel_type=CHANNEL_TYPE_EMAIL,
                target=target,
                encrypted_config=None,
            )
            if channel is None:
                # 并发插入撞唯一约束：按已存在处理，重发验证码。
                channel = await asyncio.to_thread(
                    self._channels.find_channel_by_target,
                    user_id=user_id,
                    channel_type=CHANNEL_TYPE_EMAIL,
                    target=target,
                )
                if channel is None:  # pragma: no cover - 防御性分支
                    raise PushChannelDuplicateError("该邮箱已绑定推送渠道")
            else:
                created = True
        await email_service.send_otp(target, purpose=CHANNEL_OTP_PURPOSE)
        return channel, created

    async def create_webhook_channel(
        self,
        *,
        user_id: int,
        url: str,
        secret_box: Any,
        webhook_sender: WebhookSender,
        channel_type: str = CHANNEL_TYPE_WEBHOOK,
    ) -> tuple[dict[str, Any], bool]:
        """创建 webhook 渠道：URL 校验 → 探测投递（即验证）→ 密封落库。

        探测成功才允许落库，渠道落库即 verified；探测失败不留下不可用行。
        encrypted_config 密封 ``{"url": ...}`` 作为投递凭据；加密密钥不可用
        时 secrets 层抛 PushChannelSecretError，绝不降级为明文存储。
        """
        target = await asyncio.to_thread(validate_webhook_url, url)
        existing = await asyncio.to_thread(
            self._channels.find_channel_by_target,
            user_id=user_id,
            channel_type=channel_type,
            target=target,
        )
        if existing is not None and existing["verified"]:
            raise PushChannelDuplicateError("该 Webhook 已绑定推送渠道")
        try:
            await webhook_sender.send(
                url=target,
                title=_PROBE_WEBHOOK_TITLE,
                content=_PROBE_WEBHOOK_CONTENT,
            )
        except Exception as exc:
            raise WebhookProbeFailedError(f"Webhook 探测失败：{exc}") from exc
        if existing is not None:
            # 防御分支：历史遗留的未验证 webhook 行，探测通过后补验证。
            await asyncio.to_thread(
                self._channels.mark_channel_verified,
                user_id=user_id,
                channel_id=existing["id"],
            )
            existing["verified"] = True
            return existing, False
        encrypted_config = seal_channel_config(secret_box, {"url": target})
        channel = await asyncio.to_thread(
            self._channels.create_channel,
            user_id=user_id,
            channel_type=channel_type,
            target=target,
            encrypted_config=encrypted_config,
            verified=True,
        )
        if channel is None:
            # 并发插入撞唯一约束：按已绑定处理。
            raise PushChannelDuplicateError("该 Webhook 已绑定推送渠道")
        return channel, True

    async def verify_channel(
        self,
        *,
        user_id: int,
        channel_id: int,
        code: str,
        email_service: EmailService,
    ) -> dict[str, Any]:
        channel = await asyncio.to_thread(
            self._channels.get_channel,
            user_id=user_id,
            channel_id=channel_id,
        )
        if channel is None:
            raise PushChannelNotFoundError("推送渠道不存在")
        if channel["verified"]:
            return channel
        ok = await email_service.verify_otp(
            channel["target"],
            code,
            purpose=CHANNEL_OTP_PURPOSE,
        )
        if not ok:
            raise InvalidChannelOtpError("验证码错误或已过期")
        await asyncio.to_thread(
            self._channels.mark_channel_verified,
            user_id=user_id,
            channel_id=channel_id,
        )
        channel["verified"] = True
        return channel

    def list_channels(self, *, user_id: int) -> list[dict[str, Any]]:
        return self._channels.list_channels(user_id)

    def set_channel_status(
        self,
        *,
        user_id: int,
        channel_id: int,
        status: str,
    ) -> dict[str, Any]:
        updated = self._channels.set_channel_status(
            user_id=user_id,
            channel_id=channel_id,
            status=status,
        )
        if not updated:
            raise PushChannelNotFoundError("推送渠道不存在")
        channel = self._channels.get_channel(user_id=user_id, channel_id=channel_id)
        if channel is None:  # pragma: no cover - 防御性分支
            raise PushChannelNotFoundError("推送渠道不存在")
        return channel

    def delete_channel(self, *, user_id: int, channel_id: int) -> None:
        deleted = self._channels.delete_channel(user_id=user_id, channel_id=channel_id)
        if not deleted:
            raise PushChannelNotFoundError("推送渠道不存在")

    async def send_test_email(
        self,
        *,
        user_id: int,
        channel_id: int,
        email_service: EmailService,
    ) -> dict[str, Any]:
        """经真实 SMTP 管线向已验证渠道发送一封测试简报邮件。"""
        channel = await asyncio.to_thread(
            self._channels.get_channel,
            user_id=user_id,
            channel_id=channel_id,
        )
        if channel is None:
            raise PushChannelNotFoundError("推送渠道不存在")
        if not channel["verified"]:
            raise PushChannelNotVerifiedError("推送渠道尚未验证")
        if channel["status"] != CHANNEL_STATUS_ACTIVE:
            raise PushChannelDisabledError("推送渠道已停用")
        if channel["channel_type"] != CHANNEL_TYPE_EMAIL:
            raise PushChannelNotFoundError("推送渠道不存在")
        await email_service.send_briefing(
            channel["target"],
            _TEST_BRIEFING_CONTENT,
            source="all",
            period="daily",
            date_str="渠道测试",
        )
        return channel

    async def send_test_message(
        self,
        *,
        user_id: int,
        channel_id: int,
        email_service: EmailService | None = None,
        secret_box: Any = None,
        webhook_sender: WebhookSender | None = None,
        telegram_sender: Any | None = None,
    ) -> dict[str, Any]:
        """按渠道类型分发测试投递：email 走 SMTP，webhook/discord 走平台载荷，
        telegram 走 Bot API（chat_id 仅存在于密封配置）。"""
        channel = await asyncio.to_thread(
            self._channels.get_channel,
            user_id=user_id,
            channel_id=channel_id,
        )
        if channel is None:
            raise PushChannelNotFoundError("推送渠道不存在")
        if channel["channel_type"] == CHANNEL_TYPE_EMAIL:
            return await self.send_test_email(
                user_id=user_id,
                channel_id=channel_id,
                email_service=email_service,
            )
        if not channel["verified"]:
            raise PushChannelNotVerifiedError("推送渠道尚未验证")
        if channel["status"] != CHANNEL_STATUS_ACTIVE:
            raise PushChannelDisabledError("推送渠道已停用")
        config = await asyncio.to_thread(
            unseal_channel_config,
            secret_box,
            channel["encrypted_config"] or "",
        )
        if channel["channel_type"] == CHANNEL_TYPE_TELEGRAM:
            if telegram_sender is None:
                raise TelegramNotConfiguredError("Telegram 推送未启用")
            await telegram_sender.send_message(
                chat_id=str(config.get("chat_id") or ""),
                title=_TEST_WEBHOOK_TITLE,
                content=_TEST_WEBHOOK_CONTENT,
            )
            return channel
        if channel["channel_type"] not in {CHANNEL_TYPE_WEBHOOK, CHANNEL_TYPE_DISCORD}:
            raise PushChannelNotFoundError("推送渠道不存在")
        if webhook_sender is None:  # pragma: no cover - 防御性分支
            raise PushChannelNotFoundError("推送渠道不存在")
        await webhook_sender.send(
            url=str(config.get("url") or ""),
            title=_TEST_WEBHOOK_TITLE,
            content=_TEST_WEBHOOK_CONTENT,
        )
        return channel
