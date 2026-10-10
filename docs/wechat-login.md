# 微信网站扫码登录

登录窗口的「使用微信登录」进入 `/oauth/wechat?redirect=<站内目标>`。
页面嵌入微信官方二维码，支持重新加载、有效期到期刷新、打开官方页面及切换其他登录方式。
微信入口仍由现有 `/api/features` 配置决定；未配置时不显示入口，直达页面会显示暂不可用。

## 平台配置

使用微信开放平台**已审核且有微信登录权限的网站应用** AppID 和 AppSecret。
已认证服务号、支付商户号、APIv3 密钥和支付证书不能替代网站应用登录凭据。
网站应用凭据的位置可参考[腾讯官方 PC 微信登录说明](https://cloud.tencent.com/document/product/1441/62649)。

在运维后台「OAuth 登录」填写网站应用 AppID、AppSecret，并启用微信渠道。
以 `https://aigcnews.cn` 为公网基址时，授权回调域为 `aigcnews.cn`，完整回调为：

```text
https://aigcnews.cn/api/auth/oauth/wechat/callback
```

使用备用入口时，该入口也需要微信平台允许对应回调域名。
凭据只保存于后端 OAuth 配置，页面不接触 AppSecret；不要填进源码或前端环境变量。
已有会员应先用原登录方式进入账号，在账户设置中绑定微信，再使用扫码登录。
全新微信身份首次登录会按现有规则创建账号，不会凭昵称合并已有账号。

## 协议与验证

- 新增 `POST /api/auth/oauth/{provider}/start?redirect_to=...`：返回
  `authorization_url` 和 `expires_in`，设置 HttpOnly / Secure / SameSite=Lax 浏览器绑定 cookie，禁止缓存。
- 原有 `GET` 保持 307 重定向；POST 与 GET 共用现有 state、回调和 handoff 逻辑。
- 官方 iframe 使用 `login_type=jssdk&self_redirect=false`，成功后在顶层窗口进入原 OAuth 回调流程。
- 授权地址仅允许 `https://open.weixin.qq.com/connect/qrconnect`；state 在 Redis 中限时、一次性消费，
  回调与登录 handoff 均校验浏览器绑定，保留站内返回路径。
- 配置完成后需实测扫码确认、取消/重试、过期刷新，以及已有账号绑定后的会员状态。
