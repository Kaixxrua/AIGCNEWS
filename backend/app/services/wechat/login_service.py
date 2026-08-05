from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

from backend.app.domain.wechat_secret_box import WeChatSecretBoxError
from backend.app.repositories.wechat_session_repository import (
    WeChatLoginAttemptRepository,
    WeChatSessionRepository,
)
from backend.app.services.wechat.errors import (
    WeChatAccountContextError,
    WeChatLoginFailed,
    WeChatQrExpired,
    WeChatSessionExpired,
    WeChatUpstreamError,
)
from backend.app.services.wechat.parser import extract_account_info_from_home, map_scan_status
from backend.app.services.wechat.transport import (
    WeChatMpTransport,
    _build_cookie_header,
    _merge_cookie_dict,
)

logger = logging.getLogger(__name__)


def _session_to_summary(session: dict[str, Any] | None) -> dict[str, Any]:
    if session is None:
        return {
            "connected": False,
            "status": "disconnected",
            "account_name": "",
            "account_avatar_url": "",
            "last_validated_at": None,
            "last_used_at": None,
            "expires_at": None,
            "invalid_reason_code": None,
        }
    return {
        "connected": session.get("status") == "active",
        "status": session.get("status", "disconnected"),
        "account_name": session.get("account_name", ""),
        "account_avatar_url": session.get("account_avatar_url", ""),
        "last_validated_at": session.get("last_validated_at"),
        "last_used_at": session.get("last_used_at"),
        "expires_at": session.get("expires_at"),
        "invalid_reason_code": session.get("invalid_reason_code"),
    }


class WeChatLoginService:
    """Orchestrates the WeChat MP QR login flow."""

    def __init__(
        self,
        attempt_repository: WeChatLoginAttemptRepository,
        session_repository: WeChatSessionRepository,
        transport: WeChatMpTransport,
        *,
        login_attempt_ttl_seconds: int = 300,
    ) -> None:
        self._attempts = attempt_repository
        self._sessions = session_repository
        self._transport = transport
        self._attempt_ttl = login_attempt_ttl_seconds

    def _now(self) -> datetime:
        return datetime.now(timezone.utc)

    async def start_login_attempt(self, owner_id: int) -> dict[str, Any]:
        attempt_id = uuid4()
        session_id = f"{int(self._now().timestamp() * 1000)}{secrets.randbelow(100)}"
        try:
            response = await self._transport.start_login(session_id)
        except WeChatSecretBoxError as exc:
            raise WeChatUpstreamError("微信加密配置未就绪") from exc

        cookies = response.cookies
        uuid_cookie = _build_cookie_header({k: v for k, v in cookies.items() if k == "uuid"})
        if not uuid_cookie:
            logger.warning("startlogin did not return uuid cookie")
            raise WeChatLoginFailed("未获取到微信登录会话")

        expires_at = self._now() + timedelta(seconds=self._attempt_ttl)
        attempt = self._attempts.create_login_attempt(
            owner_id,
            attempt_id,
            {
                "uuid_cookie": uuid_cookie,
                "expires_at": expires_at.isoformat(),
            },
        )
        return {
            "attempt_id": attempt["attempt_id"],
            "status": attempt["status"],
            "expires_at": attempt["expires_at"],
        }

    async def get_qr_code_image(self, owner_id: int, attempt_id: UUID) -> tuple[bytes, str]:
        # Validate ownership/existence without needing the secret cookie.
        attempt = self._attempts.get_login_attempt(owner_id, attempt_id)
        if attempt is None or self._is_expired(attempt):
            raise WeChatQrExpired()

        uuid_cookie = attempt.get("uuid_cookie", "")
        cookies = dict(
            item.strip().split("=", 1)
            for item in uuid_cookie.split(";")
            if "=" in item
        )
        random_value = str(int(self._now().timestamp() * 1000))
        response = await self._transport.get_qr_code(random_value, cookies=cookies)
        content_type = response.headers.get("content-type", "image/png")
        return response.content, content_type

    def _is_expired(self, attempt: dict[str, Any]) -> bool:
        expires_at = attempt.get("expires_at")
        if not expires_at:
            return True
        try:
            if isinstance(expires_at, datetime):
                deadline = expires_at
            else:
                deadline = datetime.fromisoformat(expires_at)
            if deadline.tzinfo is None:
                deadline = deadline.replace(tzinfo=timezone.utc)
            return deadline < self._now()
        except (TypeError, ValueError):
            return True

    async def get_login_status(self, owner_id: int, attempt_id: UUID) -> dict[str, Any]:
        attempt = self._attempts.get_login_attempt(owner_id, attempt_id)
        if attempt is None or self._is_expired(attempt):
            raise WeChatQrExpired()

        uuid_cookie = attempt.get("uuid_cookie", "")
        cookies = dict(item.strip().split("=", 1) for item in uuid_cookie.split(";") if "=" in item)
        try:
            response = await self._transport.ask_scan_status(cookies=cookies)
            body = response.json()
        except WeChatSecretBoxError as exc:
            raise WeChatUpstreamError("微信加密配置未就绪") from exc

        status, metadata = map_scan_status(body)
        self._attempts.update_login_attempt(
            owner_id,
            attempt_id,
            {
                "status": status,
                "upstream_status": metadata.get("upstream_status"),
                "error_code": metadata.get("reason") if status == "failed" else None,
            },
        )
        return {"status": status, **metadata}

    async def complete_login(self, owner_id: int, attempt_id: UUID) -> dict[str, Any]:
        attempt = self._attempts.get_login_attempt(owner_id, attempt_id)
        if attempt is None or self._is_expired(attempt):
            raise WeChatQrExpired()

        status = attempt.get("status")
        # Idempotent: repeated clicks after a successful completion return the
        # active session instead of a "not confirmed" or "already completed" error.
        if status == "completed":
            return _session_to_summary(self._sessions.get_wechat_session(owner_id))

        if status not in ("confirmed", "scanned_waiting_confirmation"):
            raise WeChatLoginFailed("扫码尚未确认")

        uuid_cookie = attempt.get("uuid_cookie", "")
        cookies = dict(item.strip().split("=", 1) for item in uuid_cookie.split(";") if "=" in item)
        try:
            response = await self._transport.biz_login(cookies=cookies)
            body = response.json()
        except WeChatSecretBoxError as exc:
            raise WeChatUpstreamError("微信加密配置未就绪") from exc

        from backend.app.services.wechat.parser import parse_biz_login_response

        token, _ = parse_biz_login_response(body)
        merged_cookies = _merge_cookie_dict(cookies, response.cookies)
        # The uuid cookie only belongs to the QR login handshake; the real MP
        # admin session is carried by the cookies returned after login.
        merged_cookies.pop("uuid", None)
        cookie_header = _build_cookie_header(merged_cookies)
        api_cookies = {
            item.strip().split("=", 1)[0]: item.strip().split("=", 1)[1]
            for item in cookie_header.split(";")
            if "=" in item
        }

        session = self._sessions.save_wechat_session(
            owner_id,
            {
                "token": token,
                "cookie": cookie_header,
                "status": "active",
                "account_name": "",
                "account_avatar_url": "",
                "last_validated_at": self._now().isoformat(),
                "last_used_at": self._now().isoformat(),
            },
        )

        try:
            home_response = await self._transport.fetch_home_page(
                token=token, cookies=api_cookies
            )
        except WeChatSecretBoxError as exc:
            self._sessions.mark_wechat_session_invalid(
                owner_id, "WECHAT_SESSION_EXPIRED"
            )
            raise WeChatUpstreamError("微信加密配置未就绪") from exc

        if home_response.status_code != 200:
            self._sessions.mark_wechat_session_invalid(
                owner_id, "WECHAT_SESSION_EXPIRED"
            )
            raise WeChatSessionExpired()

        account_info = extract_account_info_from_home(home_response.text())
        if not account_info.get("account_name"):
            self._sessions.mark_wechat_session_invalid(
                owner_id, "WECHAT_ACCOUNT_CONTEXT_INVALID"
            )
            raise WeChatAccountContextError()

        session = self._sessions.save_wechat_session(
            owner_id,
            {
                **account_info,
                "last_validated_at": self._now().isoformat(),
            },
        )
        self._attempts.update_login_attempt(
            owner_id,
            attempt_id,
            {"status": "completed"},
        )
        return _session_to_summary(session)

    async def get_session_summary(self, owner_id: int) -> dict[str, Any]:
        session = self._sessions.get_wechat_session(owner_id)
        return _session_to_summary(session)

    async def invalidate_session(self, owner_id: int, reason_code: str) -> dict[str, Any]:
        session = self._sessions.mark_wechat_session_invalid(owner_id, reason_code)
        return _session_to_summary(session)

    async def cancel_login_attempt(self, owner_id: int, attempt_id: UUID) -> bool:
        return self._attempts.delete_login_attempt(owner_id, attempt_id)

    async def cleanup_expired_attempts(self, owner_id: int) -> int:
        return self._attempts.expire_login_attempts(owner_id)
