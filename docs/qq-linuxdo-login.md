# QQ 与 Linux DO 快捷登录

两个渠道共用现有 OAuth 登录、一次性 state/cookie 交接和已登录账号绑定流程。
配置完整且启用后才在登录窗口、账号设置中显示入口；已绑定的身份即使暂时停用仍显示。
未申请应用时保持关闭。代码交付不代表平台审核完成或真实账号联调完成。

## 申请应用

可按以下资料申请，网站及业务描述应与实际经营内容一致：

- 应用名称：`AIGCNEWS`
- 网站首页：`https://aigcnews.cn`
- 应用简介：`提供人工智能资讯、开源项目和论文的整理、搜索及收藏服务，支持第三方账号快捷登录与账号绑定。`
- 业务补充：若申请表询问付费服务，如实说明网站包含会员服务。

QQ：登录 [QQ 互联](https://connect.qq.com/)，完成开发者资料，创建网站应用；按平台要求提交网站信息和审核材料，取得 **AppID / AppKey**。QQ 互联凭据与微信 AppID、商户号不同。

Linux DO：登录 [Linux DO Connect](https://connect.linux.do/)，进入「我的应用接入 → 申请新接入」，取得 **Client ID / Client Secret**。申请步骤见 [Linux DO 官方社区文档](https://wiki.linux.do/Community/LinuxDoConnect)。

回调必须与 Monitor 的「OAuth 公网基址」一致，使用表单中显示的完整「应用回调地址」。以基址 `https://aigcnews.cn` 为例：

| 渠道 | 回调地址 |
| --- | --- |
| QQ | `https://aigcnews.cn/api/auth/oauth/qq/callback` |
| Linux DO | `https://aigcnews.cn/api/auth/oauth/linuxdo/callback` |

如果实际基址带 `www`，需在两个平台登记相应的完整地址；不能填写前端 `/oauth/callback`。备用入口 `OAUTH_ALTERNATE_BASE_URLS` 中使用的域名也须登记同一路径的回调，例如 `https://aigcradar.online/api/auth/oauth/qq/callback`。不支持额外回调的应用应移除未登记的备用入口配置。

## 启用

1. 管理员打开 Monitor → OAuth 快捷登录，核对公网基址。
2. QQ 区块填写 AppID / AppKey；Linux DO 区块填写 Client ID / Client Secret。
3. 应用获得平台授权后，勾选相应登录方式并保存。密钥输入为空表示保留当前数据库值，勾选清除才删除。
4. 用退出登录的浏览器分别走完整授权流程；再用已有账号从账号设置发起绑定，检查返回原页面、重复登录保持同一账号。

密钥只在服务端使用，沿用 `OAUTH_CONFIG_ENCRYPTION_KEY`（未设置时使用 `WECHAT_SESSION_ENCRYPTION_KEY`）加密入库；后台仅回显脱敏值。Redis、有效公网基址、启用开关和两项凭据缺一不可。
环境变量备用配置见 `.env.example`；已有数据库配置时不会逐字段回落到环境变量。

## 身份及接口约定

- QQ 以 OpenID 为身份键，核对 `/oauth2.0/me` 返回的 client_id；不把 QQ 昵称当成邮箱。
- Linux DO 以不可变的数字 `id` 为身份键，忽略没有可信验证合同的邮箱字段及额外 API 密钥；不以用户名、信任等级或外部 ID 代替身份键。
- 两者均不自动按昵称/未验证邮箱合并已有账号。已有账号应先登录，再选择绑定，避免创建独立账号。
- 上游调用固定 HTTPS 地址，限制超时及响应体积，拒绝重定向。QQ 官方 GET 接口的密钥、令牌等查询参数从 HTTPX 请求日志中移除。
- 头像仅从明确允许的 HTTPS 头像域名尽力导入，不跟随重定向，不影响登录结果。
- 平台取消授权但不返回 code 时返回 `400 oauth_authorization_failed`；不交换令牌或写入身份。

QQ 接口依据：[授权码换取令牌](https://wiki.connect.qq.com/使用authorization_code获取access_token)、[获取 OpenID](https://wiki.connect.qq.com/获取用户openid_oauth2-0)、[用户信息](https://wiki.connect.qq.com/get_user_info)。Linux DO 端点及表单编码依据其[官方社区文档](https://wiki.linux.do/Community/LinuxDoConnect)。
