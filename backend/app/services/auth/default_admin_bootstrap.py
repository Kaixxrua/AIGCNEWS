from __future__ import annotations

import logging
from typing import Protocol

logger = logging.getLogger(__name__)

DEFAULT_ADMIN_USERNAME = "admin"


class DefaultAdminRepository(Protocol):
    """Persistence operations required by the default-admin bootstrap."""

    def get_user_count(self) -> int: ...

    def get_user_by_email(self, email: str) -> dict | None: ...

    def create_user_with_email(
        self,
        email: str,
        hashed_password: str,
        role: str = "user",
        username: str = "",
    ) -> int: ...


def ensure_default_admin(
    *,
    repository: DefaultAdminRepository,
    email: str,
    password: str,
    hash_password,
) -> bool:
    """空库引导：用户表为空时种子一个默认管理员账号，返回是否发生种子。

    开源自托管可能完全没有可用的 SMTP（注册 OTP 依赖邮件投递），此时连
    首个账号都无法注册；约定全新部署（用户表为空）首启动种子默认管理员，
    登录后通过免 SMTP 的改密端点立即轮换公开默认密码。

    - 任一配置为空 → 跳过（显式禁用种子的出口）；
    - 用户表非空 → no-op，既有部署不受影响；
    - email 唯一约束冲突容忍：多进程/并发启动竞态下视为已被种子。
    """
    normalized_email = email.strip().lower()
    if not normalized_email or not password:
        logger.info("[Startup] Default admin bootstrap disabled (empty config).")
        return False
    if repository.get_user_count() > 0:
        return False
    try:
        repository.create_user_with_email(
            normalized_email,
            hash_password(password),
            "admin",
            DEFAULT_ADMIN_USERNAME,
        )
    except Exception as exc:
        if "unique" not in str(exc).lower() and "duplicate" not in str(exc).lower():
            raise
        logger.info(
            "[Startup] Default admin %s already seeded concurrently; skipping.",
            normalized_email,
        )
        return False
    return True


def uses_configured_default_credentials(
    *,
    email: str | None,
    password: str | None,
    configured_email: str,
    configured_password: str,
) -> bool:
    """登录路径谓词：本次登录是否使用了配置里的种子默认凭据（明文比对）。

    登录已成功，明文密码等于种子密码 ⟺ 库内哈希匹配种子密码，
    因此无需再做 bcrypt。env 自定义种子密码时按同口径提示。
    """
    if not email or not password or not configured_email or not configured_password:
        return False
    return (
        email.strip().lower() == configured_email.strip().lower()
        and password == configured_password
    )


def password_change_required_for_email(
    *,
    repository: DefaultAdminRepository,
    email: str | None,
    configured_email: str,
    configured_password: str,
    verify_password,
) -> bool:
    """身份路径谓词：该账号是否仍在使用种子默认密码（按库内哈希判定）。

    只认「种子邮箱 + 种子密码」这一组配置口径：普通账号在取库前短路，
    命中的账号一次查询 + 一次 bcrypt 校验。用于 /auth/me 常驻提醒，
    改密后哈希不再匹配，标志自然消失。
    """
    if not email or not configured_email or not configured_password:
        return False
    normalized_email = email.strip().lower()
    if normalized_email != configured_email.strip().lower():
        return False
    user = repository.get_user_by_email(normalized_email)
    if user is None:
        return False
    return bool(verify_password(configured_password, str(user["hashed_password"])))
