from __future__ import annotations

from backend.app.core.config import Settings
from backend.app.domain.wechat_secret_box import (
    WeChatSecretBox,
)


def build_wechat_secret_box(settings: Settings) -> WeChatSecretBox:
    """Create the configured WeChat secret box with strict key validation.

    Raises:
        WeChatSecretBoxError: If the key is missing or invalid.
    """
    return WeChatSecretBox.from_urlsafe_base64(
        settings.wechat_session_encryption_key,
        settings.wechat_session_encryption_key_version,
    )
