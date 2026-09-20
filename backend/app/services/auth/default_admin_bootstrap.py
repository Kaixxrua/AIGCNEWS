from __future__ import annotations

import logging
from typing import Protocol

logger = logging.getLogger(__name__)

DEFAULT_ADMIN_USERNAME = "admin"
LEGACY_DEFAULT_ADMIN_EMAIL = "admin@aigcnews.internal"
LEGACY_DEFAULT_ADMIN_PASSWORD = "admin123456"


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
    首个账号都无法注册；显式配置独立强随机密码后，空库首启动种子管理员。

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
    if password == LEGACY_DEFAULT_ADMIN_PASSWORD:
        logger.error("[Startup] Refusing public default admin password; configure an independent random secret.")
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


def _bootstrap_passwords_for_email(
    email: str | None, configured_email: str, configured_password: str,
) -> set[str]:
    normalized_email = (email or "").strip().lower()
    passwords = set()
    if normalized_email and normalized_email == configured_email.strip().lower():
        passwords.add(LEGACY_DEFAULT_ADMIN_PASSWORD)
        if configured_password:
            passwords.add(configured_password)
    # Existing factory accounts still need a rotation warning after upgrading
    # to the empty password default or changing bootstrap configuration.
    if normalized_email == LEGACY_DEFAULT_ADMIN_EMAIL:
        passwords.add(LEGACY_DEFAULT_ADMIN_PASSWORD)
    return passwords


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
    return bool(password) and password in _bootstrap_passwords_for_email(
        email, configured_email, configured_password,
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

    检查配置的种子凭据与历史公开凭据；普通账号在取库前短路。
    命中的账号查询并校验哈希。用于 /auth/me 常驻提醒，
    改密后哈希不再匹配，标志自然消失。
    """
    passwords = _bootstrap_passwords_for_email(email, configured_email, configured_password)
    if not passwords:
        return False
    user = repository.get_user_by_email(email.strip().lower())
    if user is None:
        return False
    return any(verify_password(password, str(user["hashed_password"])) for password in passwords)
