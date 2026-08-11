"""微信公众号采集源插件契约。

本模块只包含公开契约：错误基类、路由消费的服务方法面 Protocol 与
服务束。扫码登录、mp.weixin.qq.com / 搜狗微信交互等敏感实现在过渡期
位于仓库内 ``services/wechat`` 与 ``services/wechat_sogou``，随后迁移至
仓库外私有包 ``aigcnews_private``。公众号文章的存储、展示与媒体代理层
始终保留在仓库内。

实现类构造约定（公共代码 dependencies.py 负责注入仓储与设置派生值）：

- ``WeChatMpTransport(proxy: str | None = None)``
- ``SogouWechatTransport()``（直连策略，不走出站代理）
- 四个 service 以仓储 / transport / 设置派生值构造，签名以实现侧为准。
"""

from __future__ import annotations

from typing import Any, NamedTuple, Protocol, runtime_checkable
from uuid import UUID


class WeChatError(Exception):
    """Base class for all WeChat backend domain errors."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


@runtime_checkable
class WeChatLoginServiceProtocol(Protocol):
    """扫码登录生命周期服务的方法面（routes_wechat 消费）。"""

    async def start_login_attempt(self, owner_id: int) -> dict[str, Any]: ...

    async def get_qr_code_image(self, owner_id: int, attempt_id: UUID) -> tuple[bytes, str]: ...

    async def get_login_status(self, owner_id: int, attempt_id: UUID) -> dict[str, Any]: ...

    async def complete_login(self, owner_id: int, attempt_id: UUID) -> dict[str, Any]: ...

    async def cancel_login_attempt(self, owner_id: int, attempt_id: UUID) -> bool: ...

    async def get_session_summary(self, owner_id: int) -> dict[str, Any]: ...


@runtime_checkable
class WeChatAccountServiceProtocol(Protocol):
    """公众号检索与保存服务的方法面（routes_wechat 消费）。"""

    async def search_accounts(
        self,
        owner_id: int,
        keyword: str,
        *,
        begin: int = 0,
        size: int = 5,
    ) -> tuple[list[dict[str, Any]], int]: ...

    async def save_account(self, owner_id: int, payload: dict[str, Any]) -> dict[str, Any]: ...

    async def list_accounts(self, owner_id: int) -> list[dict[str, Any]]: ...


@runtime_checkable
class WeChatSyncServiceProtocol(Protocol):
    """文章同步服务的方法面（routes_wechat 消费）。"""

    async def submit_sync(self, owner_id: int, account_id: int) -> dict[str, Any]: ...


@runtime_checkable
class WeChatFollowServiceProtocol(Protocol):
    """关注目录与文章流服务的方法面（routes_wechat 消费，同步方法）。"""

    def list_catalog(self, user_id: int) -> list[dict[str, Any]]: ...

    def follow(self, user_id: int, account_id: int) -> dict[str, Any]: ...

    def unfollow(self, user_id: int, account_id: int) -> dict[str, Any]: ...

    def get_feed(self, user_id: int, *, per_account: int = 5) -> list[dict[str, Any]]: ...

    def get_article_detail(self, user_id: int, account_id: int, article_id: int) -> dict[str, Any]: ...


class WeChatServiceBundle(NamedTuple):
    """WeChat 源插件暴露给公共代码的实现类集合。

    所有属性为实现类（非实例）；仓储注入与设置派生由公共代码
    dependencies.py 完成，插件不提供预连线实例。
    """

    mp_transport: type[Any]
    sogou_transport: type[Any]
    login_service: type[Any]
    account_service: type[Any]
    follow_service: type[Any]
    sync_service: type[Any]
    error: type[WeChatError]
