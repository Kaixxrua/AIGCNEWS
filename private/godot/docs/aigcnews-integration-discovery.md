# AIGCNEWS 营地接入：只读定位记录

核对时间：2026-09-11 01:42 CST 附近。只读源码、文档及匿名公开 HTTP GET；未访问 DB、密钥、cookie、账户接口，未启动服务/浏览器/Godot/build，未作 Git 或任何 AIGCNEWS 写入。本轮仅写本文。场景约8.7分后进入人物/BOSS由主代理验收决定，本记录不认定评分达标。

## 1. 关键定位：v0.1 不是找到的最新规则

- 主代理正在阅读的 [PRD v0.1 全文](E:/Projects/AIGCNEWS-local/local/reviews/contact-camp-prd-20260910/PRD-contact-camp-v0.1.md)：2026-09-10，明确“待评审”；SHA256 `c8d9d6447f949fef3bdb193ffe5f275cd9691a82d7aa1a1d139788d4527876f0`。
- **另有 [PRD v0.2 全文](E:/Projects/aigcnews_private/.claude/worktrees/camp-backend-1789017921-39896-1112/app/docs/product/contact-camp/PRD-v0.2.md)**：2026-09-10，文首标注“D01—D06 已按用户评审确认”；SHA256 `9477636a9875fea5dc7ce80f4b209b94720906b12f2ea29a50dc805b9322198b`。这是本轮找到的最新明确版本；审批状态是该文件的声明，不等于本轮重新确认审批或已部署。
- [backend-contract.md](E:/Projects/aigcnews_private/.claude/worktrees/camp-backend-1789017921-39896-1112/app/docs/product/contact-camp/backend-contract.md)：SHA256 `803d5ebc31695f0ea43b56feae729c85b85e53585c3bfce568f68bea3e79fc28`。
- [openapi.json](E:/Projects/aigcnews_private/.claude/worktrees/camp-backend-1789017921-39896-1112/app/docs/product/contact-camp/openapi.json)：20个路径；SHA256 `1f21ce7a11ce8d357b31546d13db894951e8c799a6fc7e716de42163a1c159d6`。
- [validation.md](E:/Projects/aigcnews_private/.claude/worktrees/camp-backend-1789017921-39896-1112/app/docs/product/contact-camp/validation.md) 记录基线3350472、私有开发会话、176 tests passed及隔离 PostgreSQL 验证，并明确**没有部署营地代码、迁移或开关到生产**。这是历史验证记录，本审查未重跑，不能冒充当前部署验证。

已读本工作区根 AGENTS、AIGCNEWS-local 根 AGENTS、上述私有 app/AGENTS；private/guest 未发现根 AGENTS。私有文档要求营地实现及迁移留在私有 app/，不要同步公开仓；本轮没有执行其开发会话/提交/部署命令。已停止扫描部署快照，后续定位限定上述源码和文档。

### v0.1 → v0.2 实质差异

| 项目 | v0.1 草案 | v0.2 及已读代码 |
| --- | --- | --- |
| 每日上限 | 前3轮奖励，之后仍可战斗 | **每天最多完成3个账户轮次**，之后仅可环境/伙伴演示 |
| BOSS刷新 | 结算后自动下一轮 | 第一只立即；后续至少冷却300秒，再由合格心跳创建 |
| 联系区 | 固定可见 | 默认展开、可折叠；登录偏好跟账户，访客本机保存；保留展开入口 |
| 稀有度 | 统一池 | 首版仍统一等概率；R/SR/SSR/UR和UR内10%独特仅预留、未启用 |

因此不能按v0.1直接重做后端；请主代理先亲读v0.2和契约，确认其为本次接入依据。

## 2. 当前运行联系页：没有发布 PRD，也未暴露 camp catalog

匿名、无认证头/会话的定点GET结果：

| 地址 | 结果 |
| --- | --- |
| `http://127.0.0.1:18783/api/site/contact-page` | 200，enabled=true，标题“联系与合作”，updated_at=`2026-08-14T16:49:28.797065+08:00` |
| `http://127.0.0.1:18784/api/site/contact-page` | 同上；body_markdown为简短公开联系方式，**不是PRD** |
| 两入口 `/api/camp/catalog` | 均404；未获得运行中的营地玩法/版本 |

不能把联系页配置更新时间当PRD版本。404与“尚未部署”的历史记录相符，但只证明这两个入口未提供该路由，不证明所有机器/隐藏服务均无camp。18785、4231未取得公开联系JSON，未继续探测。未读其他账户或管理员API。

联系配置链已核对：`contactPageApi.ts` GET `/site/contact-page` → FastAPI `routes_site.py` → `SiteContactPageResponse` / `SiteContactPage` → `PostgresSiteContactPageRepository` 的 `site_contact_page(id=1)`。字段包括enabled/nav_label/title/subtitle/service_cards/contact_entries/body_markdown/updated_at；未启用不公开草稿。只读源码，不查询数据库。

本地 [ContactPageView.vue](E:/Projects/AIGCNEWS-local/frontend/src/views/ContactPageView.vue) 明确只呈现场景与联系条目，不再显示service_cards或Markdown正文，后台字段/API仍保留。[ContactHeroVisual.vue](E:/Projects/AIGCNEWS-local/frontend/src/components/contact/ContactHeroVisual.vue) 仍是动态导入Three.js ContactFieldScene的装饰壳、主题昼夜、离屏暂停及静态降级；不是Godot营地账户前端。所检查local/guest的API源码未发现camp接线，local前端未发现camp接口调用。没有用磁盘源码推定当前HTTP部署的精确commit或整个前端字节一致。

## 3. 已存在的实现与接入契约

实现根：`E:/Projects/aigcnews_private/.claude/worktrees/camp-backend-1789017921-39896-1112/app/`。

已直接读 `backend/app/api/routes_camp.py`、main.py接线、services/camp的models/service/admin相关实现及迁移结构，不是只凭PRD推测：

- main.py注册`/api/camp`与`/api/ops/camp`，生命周期接入CampRewardWorker；services/camp已有models.py、service.py、store.py、admin.py、worker.py。
- `0067_contact_camp.sql`已有config/catalog/players/daily/collection/rounds/rewards/operations/events/admin_audit独立表，账户关联现有users；含单活跃轮次、每日单次VIP及余额/每日额度约束。未确认任何真实DB已应用迁移。
- 源码常量：600000ms一轮、300秒冷却、每日3轮、0.005概率、72小时、30秒心跳、45秒租约、10印记兑换。严格请求模型拒绝额外字段；功能总开关默认false。
- 公开`GET /api/camp/catalog`只查配置与资产池，给出rules、asset_key、pool_ids及概率；其余账户操作沿用Bearer身份，不允许前端指定目标user_id。
- 账户API已存在：GET me、history/{rewards|operations}、rounds；POST control、heartbeat、summons、redemptions；PATCH preferences；PUT team。运营配置/资产/记录/重试/指标路由也已存在，无需造假接口。
- **GET me并非纯读取**：`CampService.state()`先`retry_rewards(...limit=3)`再取state，可能发放已确认奖励。本轮没有调用它；今后只读诊断也不能仅凭GET方法认定无副作用。

### 玩法逻辑摘要（以v0.2为依据）

- **资源/收藏**：6英雄+6宠物；初始游侠/小鹿；逻辑键`hero_ranger`、`pet_deer`及`boss_ancient_guardian`。新资产通过catalog键映射，不要求重写后端或把后端当远程素材抓取器。每日免费1抽、生效会员额外2抽；重复转1印记，10印记兑换未拥有项；首版没有稀有度收益。
- **升级**：无战力等级、装备强化或角色升级加速。会员升级当天只补一次两抽；72小时会员是现有free/member权益，不创建第二套游戏VIP权限。
- **挂机/战斗**：主动开启后全站前台可见、联网的允许页面计时，静止阅读可计时；隐藏/离线不推进。30秒心跳，间隔>45秒重建基线；首次/接管/返回前台不补时间。同账户多端最多一份进度。战斗固定600秒，没有死亡惩罚、点击输出或伙伴加速。
- **BOSS**：每天完成最多3轮；轮间300秒冷却可离线经过，战斗不可离线推进。每轮自动1印记，最多一次/日0.5% VIP中奖；北京时间归属完成日，跨日保留进度和未结束冷却。前端`round:null`不能自己生成可领奖BOSS。
- **持久化/奖励**：原账户保存暂停、偏好、伙伴、收藏、余额、轮次和记录；客户端本地存储不是权威。先保存结果再事务发放，不因重试重抽；pending保留原奖励日。免费/过期获72小时、限期续72小时、长期获10替代印记，游戏不生成付费订单。
- **前端契约**：站点应用层保留session UUID及递增sequence，pathname不带query/hash；按可见性同步、遵从session_in_use/retry_after_seconds。召唤/兑换超时使用同一request UUID及同一内容。Godot仅呈现服务端round进度及结果，不上报权威伤害/中奖/余额，也不把天气动画clock当有效阅读时间。
- **保护和集成边界**：保留`/contact`开关及原联系方式来源；非营地内容页不加载完整场景，联系/文字功能不等Godot启动。认证、规则、发奖留站点后端；Godot与站点的具体嵌入/消息桥尚需设计，当前没有证据表明已实现。部署、DB迁移、开启灰度均需另行授权与验证；不能把本次只读发现当部署许可。

## 4. v97加载异常：有证据的范围与待证原因

主代理提供v97 load200753ms，对比v96 normal27277ms：约7.36倍、增加173476ms。v97这一数值本轮未在既有磁盘日志找到，按主代理实际观察记录；不伪造对应download/scene分项。

直接证据：

- [v96记录](E:/Projects/Godot-Octopath2/godot/docs/verification-v96.md) 的普通页27.277s、download2.551s、scene3.785s；**同版首次诊断页曾119.846s**。此前已有很大的首轮/页面条件差异，不能拿单次重开证明原因或性能保持。
- [v97记录](E:/Projects/Godot-Octopath2/godot/docs/verification-v97.md) 的candidate1为138.006s、download2.723s、scene6.186s及CDP超时。两项已记录时间远小于总就绪时间，主要未归因时段在其余启动/首帧等待；这些分项属于candidate1，不能移用给candidate2的200.753s。
- `artifacts/v96/web-payload.json`与v97：WASM、index.js、controls JS/CSS的SHA完全相同；PCK仅增加10828bytes、gzip增加10628bytes。包体增量本身不支持解释数分钟额外下载；网络/解压/缓存状态仍无分段轨迹可排除。
- [meadow-controls.js](E:/Projects/Godot-Octopath2/godot/web/meadow-controls.js:23) 的loadMs要等engine.startGame完成、sceneReady信号以及**两次requestAnimationFrame**；不是纯下载计时，也不是严格GPU像素验收。隐藏页/调度停顿可能延迟该指标，但本轮没有当时visibility证据。
- scene_ready_ms仅测`meadow_scene._ready()`内部；不覆盖全部资源装载/渲染启动，parent.ready后的fringe构建也不在其中。新relief是1365顶点/2560三角形，新增day shader需要实际编译/渲染；桥接每帧3个uniform写入、只在目标shader改变时复制参数，不能声称零成本，也没有证据把数分钟归到这三次写入。

建议独立排查优先级（仅建议，不开新任务/运行）：①启动到首帧之间的shader/驱动编译、资源GPU上传及主线程长任务，旧版首次诊断也慢支持优先测冷暖差异，但未证实根因；②窗口/标签可见性、RAF调度与CPU/GPU竞争，需当时状态或时间线；③WASM实例化/解包/场景CPU构建，需分段时间，不能仅凭三角形数推断；④网络/缓存，先看实际传输时序，包体增量证据使“素材变大导致7倍下载”缺乏支持。

**CDP超时只是自动化请求未及时完成，不是场景终止，也不能据此判死锁或重启。** 没有浏览器时间线/驱动编译分段，本轮只能缩小范围，不能给确定根因、FPS保持或加载优化结论。后续接入应保持联系与文本操作独立于大场景加载，不能让这段等待阻塞账户/联系功能。
