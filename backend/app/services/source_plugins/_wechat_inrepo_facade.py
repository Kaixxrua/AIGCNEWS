"""过渡期仓库内 WeChat 实现门面。

把分散在 ``services/wechat`` 与 ``services/wechat_sogou`` 的实现类聚合
为单一模块属性面，与私有包 ``aigcnews_private.sources.wechat_facade``
形状一致。实现迁移私有包后本模块删除；公共代码不得直接导入本模块，
一律经 ``source_plugins.loader.load_wechat_bundle`` 获取。
"""

from backend.app.services.wechat.account_service import WeChatAccountService
from backend.app.services.wechat.errors import WeChatError
from backend.app.services.wechat.follow_service import WeChatFollowService
from backend.app.services.wechat.login_service import WeChatLoginService
from backend.app.services.wechat.sync_service import WeChatSyncService
from backend.app.services.wechat.transport import WeChatMpTransport
from backend.app.services.wechat_sogou.transport import SogouWechatTransport

__all__ = [
    "SogouWechatTransport",
    "WeChatAccountService",
    "WeChatError",
    "WeChatFollowService",
    "WeChatLoginService",
    "WeChatMpTransport",
    "WeChatSyncService",
]
