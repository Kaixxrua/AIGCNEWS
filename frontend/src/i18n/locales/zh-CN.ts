import { enUS } from './en-US'

const overrides = {
  infrastructure: { appName: 'AIGC 新闻', loading: '加载中…', unavailable: '暂不可用' },
  common: { confirm: '确认', cancel: '取消', save: '保存', close: '关闭', retry: '重试', search: '搜索', noData: '暂无数据', language: '语言', chinese: '中文', english: 'English', back: '返回', edit: '编辑', delete: '删除', refresh: '刷新', refreshing: '刷新中…', loading: '加载中…', processing: '处理中…', send: '发送', previous: '上一页', next: '下一页', page: '页', unknown: '未知', never: '从未' },
  navigation: { home: '首页', dashboard: '仪表盘', papers: '论文', projects: '项目', chat: '对话', report: '报告', mcp: 'MCP 接入', monitor: '监控', loginAccount: '登录账号', logout: '退出登录' },
  search: { placeholder: '搜索论文、项目…', noResults: '无匹配结果', resultCount: '搜索结果 · {count} 条', trending: '今日热门推荐', paper: '论文', github: 'GitHub', news: '新闻', producthunt: 'PH', hackernews: 'HN' },
  footer: { poweredBy: '由 {brandName} 提供支持', disclaimer: '免责声明', privacy: '隐私政策', mcp: 'MCP 接入', ecosystem: '生态合作联系：' },
  auth: {
    login: '登录', logout: '退出登录', username: '用户名', password: '密码', email: '邮箱', otp: '验证码', newPassword: '新密码', confirmPassword: '确认密码',
    loginTitle: 'AIGC 资讯 · 登录', loginDescription: '欢迎回来，请登录您的账号', registerTitle: 'AIGC 资讯 · 注册', registerDescription: '创建您的账号，开启 AI 资讯之旅', forgotTitle: 'AIGC 资讯 · 重置密码', forgotDescription: '通过邮箱验证码设置新密码',
    emailPlaceholder: 'you@example.com', passwordPlaceholder: '请输入密码', otpPlaceholder: '6 位数字验证码', newPasswordPlaceholder: '至少 6 个字符', confirmPasswordPlaceholder: '再次输入密码',
    fillEmailPassword: '请填写邮箱和密码', loginFailed: '登录失败，请检查邮箱和密码', loggingIn: '登录中…', forgotPassword: '忘记密码？', noAccount: '还没有账号？', registerNow: '立即注册', hasAccount: '已有账号？', goLogin: '去登录', rememberPassword: '想起密码了？', backToLogin: '返回登录',
    getOtp: '获取验证码', resendOtp: '重新获取({countdown}s)', invalidEmail: '请输入正确格式的邮箱地址', invalidEmailGeneric: '请输入有效的邮箱地址', invalidOtp: '验证码应为 6 位数字', passwordMin: '密码至少需要 6 个字符', passwordMismatch: '两次密码输入不一致', agreeTerms: '我已阅读并同意', terms: '《用户协议与免责声明》', and: '及', termsSuffix: '，包括但不限于 AI 内容免责、禁止违法输入等条款', agreeAria: '同意用户协议与免责声明',
    registering: '注册中…', register: '注册', reset: '重置密码', resetting: '重置中…', rateLimited: '请 60 秒后再试', otpSent: '验证码已发送，请查收邮件', otpSentIfRegistered: '如果该邮箱已注册，验证码将发送至该邮箱', sendOtpFailed: '发送验证码失败，请稍后再试', registerSuccess: '注册成功！正在为您自动登录…', registerFailed: '注册失败，请稍后再试', mustAgree: '请阅读并同意《用户协议与免责声明》后再注册', resetSuccess: '密码重置成功，即将返回登录页…', resetFailed: '密码重置失败，请稍后再试',
  },
  dashboard: { title: '仪表盘', sourceRanking: '查看 {source} 排行榜', rankingSources: '排行榜来源', daily: '日榜', weekly: '周榜', monthly: '月榜', dailyOnly: '仅日榜', liveDraft: '实时初榜 · 数据仍在采集中', finalized: '榜单已定稿 · 历史名次永久归档', collecting: '实时数据正在采集，请稍候。', collectingHint: '采集完成后条目会自动进入榜单。', historyEmpty: '该日期没有此周期的榜单数据。', historyEmptyHint: '当天可能尚未采集该周期，或数据未归档。', untitled: '（无标题）', aiScore: 'AI 评分', embargoTitle: '昨日榜单正在定稿', embargoDescription: '最终榜单将在今天 {time}（{timezone}）发布。', archiving: '正在归档数据…', noDateData: '该日期暂无数据。', chooseOtherDate: '请在日历中选择其他日期。', previousMonth: '上个月', nextMonth: '下个月', stats: { total: '全部', papers: '论文', github: 'GitHub', news: '新闻', products: '产品', hn: 'HN', users: '用户', newDocuments: '新增文档' }, score: { votes: '{count} 票', points: '{count} 分' }, modules: { llm: '大模型', agents: '智能体', multimodal: '多模态', evaluation: '评测', engineering: '工程', rag: 'RAG' } },
  projects: { searchPlaceholder: '搜索名称、网站、描述、语言或标签', sort: '排序', sourceFilter: '来源筛选', categoryFilter: '项目分类筛选', primaryCategoryFilter: '一级分类筛选', subcategoryFilter: '二级分类筛选', personalTagFilter: '个人标签筛选', all: '全部', recommended: '站长推荐', today: '今日热门', clearTag: '清除标签', pageSummary: '第 {page} / {totalPages} 页 · 共 {total} 条', pagination: '项目分页', previous: '上一页', next: '下一页', visitWebsite: '访问网站', openWebsite: '打开收藏网站', openRepository: '打开 GitHub 仓库', unavailable: '仓库不可用', favorite: '收藏', loginFavorite: '登录收藏', favorited: '已收藏', added: '已加入', edit: '编辑', delete: '删除', fallbackWebsite: '该网站暂无描述。', fallbackProject: '该项目暂无描述。', stars: '{count} stars', forks: '{count} forks', todayGrowth: '今日 +{count}', loginAction: '登录', addWebsite: '添加网站', results: '{count} 条结果', emptyTitle: '没有匹配内容', emptyDescription: '请调整搜索词或筛选条件后重试。' },
  chat: { assistant: 'RAG 助手', memory: '记忆：{turns} 轮 · T={temperature}', history: '会话历史', newConversation: '新建会话', noMessage: '暂无消息', noHistory: '暂无历史会话', startTitle: '开始对话', startDescription: '提出问题，RAG 助手会基于知识库回答并附上引用。', placeholder: '输入问题…（Enter 发送，Shift+Enter 换行）', uploading: '上传中…', addAttachment: '添加附件', stop: '停止生成', thinking: '深度思考中', thought: '思考完成', thoughtDuration: '已思考 {seconds} 秒', retrieving: '正在检索并生成…', regenerate: '重新生成', delete: '删除', references: '{count} 个引用', searching: '正在搜索来源…', reranking: '正在重排匹配项…', answering: '正在生成回答…', requestError: '请求失败' },
  report: { period: { daily: '日报', weekly: '周报', monthly: '月报' }, titleFallback: '自动化简报', cached: '已缓存', generating: '生成中', subscribe: '订阅', unsubscribe: '取消订阅', sendBriefing: '发送简报', manageSubscriptions: '管理订阅', following: '跟随', unlocked: '解锁', regenerate: '重新生成', generate: '生成', dailyOnly: '仅日报', selectType: '选择类型查看简报', backToBottom: '回到底部', later: '稍后', goLogin: '去登录', subscribed: '已订阅' },
  paper: { back: '返回', conversation: '对话', newConversation: '新建会话', noHistory: '暂无历史会话', delete: '删除', placeholder: '输入问题…（Enter 发送）', unavailableTitle: '服务暂未开放，敬请期待', unavailableDescription: '论文旁 AI 对话功能正在维护升级中，当前暂不可使用。', loadFailed: '论文加载失败', originalLink: '原始链接 ↗', renderingPages: '渲染 {loaded}/{total} 页', downloadPdf: '下载 PDF', captured: '已截取区域，向 AI 提问', previewAlt: '截图预览', visionPlaceholder: '例如：请解释这个图表的含义…', send: '发送', cancel: '取消', pdfUnavailable: 'PDF 暂未就绪', viewOriginal: '在 arXiv/HuggingFace 上查看 ↗' },
  monitor: { title: '运维监控', subtitle: '任务历史 · 调度器状态 · 数据管理', sync: '立即同步', syncing: '同步中…', taskRunning: '任务运行中…', forceSync: '强制同步', generateDaily: '生成每日简报', generating: '生成中…', cacheTitle: '清除仪表盘 Redis 缓存，强制下次请求重新读取数据库', refreshCache: '刷新仪表盘缓存', clearing: '清除中…', clearData: '清空数据', clearConfirmTitle: '确认清空所有数据', clearDeletes: '此操作将永久删除：', clearSqlite: 'SQLite 中所有文档和任务记录', clearMilvus: 'Milvus 向量索引数据', irreversible: '此操作不可逆，清空后无法恢复！', confirmClear: '确认清空', dateIngestion: '按日期采集数据', targetDate: '目标日期：', startIngestion: '开始采集', ingesting: '采集中…', dateHint: '将采集指定日期的 arXiv 论文、GitHub 项目、HuggingFace 模型及 AI 新闻。', sourceIngestion: '按数据源采集', sourceHint: '点击任意源独立触发采集，不影响其他源。' },
  legal: { back: '返回', updated: '最后更新：2026 年 3 月', disclaimerTitle: '用户协议与免责声明', disclaimerMeta: '最后更新：2026 年 3 月 · 请在注册前仔细阅读本协议全文', privacyTitle: '隐私政策',
    disclaimer: {
      aiTitle: '一、AI 生成内容免责声明（最重要）', aiWarning: '本平台提供的 AI 资讯简报及 RAG 问答服务依托大语言模型（LLM）技术。受技术特性限制，模型可能产生听起来合理但错误、过时或虚构的内容。平台不对准确性、完整性、客观性及适用性作任何明示或暗示保证。', aiReference: '所有内容，包括代码片段、资讯摘要、数据分析及研究解读，仅供参考与学术交流，不构成投资、法律、医疗或专业工程建议。', aiLiability: '用户依据生成内容作出决策所产生的直接、间接、偶然或连带损失均由用户自行承担。', aiAcceptance: '使用本平台即表示您理解 AI 技术局限，并同意在依赖生成内容前独立核实。',
      conductTitle: '二、用户行为规范与禁止事项', conductIntro: '使用 RAG 对话、资讯检索等功能时，您同意遵守以下规则：', conduct1: '不得提交违反适用法律法规的内容，包括鼓吹暴力颠覆或分裂国家的内容。', conduct2: '不得提交色情、淫秽、赌博、暴力、恐怖主义或仇恨内容。', conduct3: '不得提交虚假信息、诽谤材料或侵犯隐私的内容。', conduct4: '不得尝试提示词注入、越狱或其他绕过平台安全机制的方法。', conduct5: '不得将生成内容用于欺诈、诈骗或其他违法活动。', conductWarning: '如用户故意违反规定或诱导 AI 生成违法内容，一切法律责任由用户独立承担。平台可立即封禁账号、保存相关日志并依法报告。',
      ipTitle: '三、知识产权声明', upstream: '上游来源：原始论文（arXiv）、开源项目（GitHub）、科技新闻（Techmeme）、产品信息（Product Hunt）及社区讨论（Hacker News）的权利归原作者或原平台所有。平台仅提供链接与 AI 辅助摘要，不主张所有权。权利方可联系 kaixxrua@gmail.com，核实后将及时处理。', generated: '平台生成内容：用户将 AI 简报或问答结果用于商业用途时，应自行评估并承担版权风险，平台不提供商业用途担保。', scraping: '自动抓取：未经书面许可，不得批量抓取简报、排行或其他 AI 生成内容。恶意或高频接口访问可能被追究法律责任。',
      serviceTitle: '四、服务变更、中断与收费权利', serviceIntro: '鉴于 AI 技术及算力成本变化，平台保留下列权利且无需承担赔偿责任：', service1: '修改或限制服务，包括对话次数、采集频率或模块可用性。', service2: '因技术故障、上游限制、政策要求或不可抗力暂停或终止部分或全部服务。', service3: '未来可对高级功能收费，并提前在平台通知。', service4: '可随时更新本协议；重大变更会公告，继续使用即视为接受最新条款。',
      accountTitle: '五、账号安全与责任归属', account1: '请妥善保管邮箱、密码和验证码。账号下的对话、订阅及 AI 使用均视为您的行为并由您负责。因凭证泄露或账号被盗造成的损失，平台不承担责任。', account2: '适用法律要求时，平台可要求手机或实名认证；拒绝可能导致部分或全部 AI 功能受限。', account3: '注册时应提供有效邮箱。服务通知及订阅简报可能发送至该邮箱，因邮箱无效而错过通知的风险由您承担。', contactTitle: '联系 · 版权与合规', contactText: '版权投诉、下架申请、违规举报或合作咨询，请联系：', effective: '本协议自 2026 年 3 月起生效。继续使用平台即表示您已阅读、理解并接受全部条款。'
    },
    privacy: {
      collectTitle: '我们收集的信息', collectIntro: '我们不收集不必要的个人信息。注册时仅收集最低限度的必要信息：', email: '邮箱地址：用于注册、登录验证及订阅简报等服务通知。', password: '密码（哈希存储）：密码使用 bcrypt 不可逆哈希，我们无法恢复明文。', logs: '访问日志：IP 地址仅用于统计每日独立访客，48 小时后自动删除且不与账号关联。', aiTitle: 'AI 对话中的数据处理', aiText: '“新对话”中的内容会匿名化后发送给 OpenAI、Anthropic 等第三方大语言模型服务商生成回答，请求不包含账号信息或个人标识。', aiWarning: '请勿输入身份证号、手机号、银行卡号、商业机密等个人或敏感信息。该数据受第三方 LLM 服务商隐私政策约束，超出平台控制范围。', useTitle: '我们如何使用信息', use1: '邮箱仅用于登录验证及在您主动订阅后发送简报。', use2: '对话记录存储在平台服务器以展示历史，并在超过保留期限后自动删除。', use3: '我们不会向第三方出售或出租您的信息。', use4: '我们不会使用对话内容投放广告或进行商业画像。', securityTitle: '存储与安全', security1: '账号数据存储于私有服务器的 MySQL 数据库，并通过 HTTPS/TLS 加密传输。我们采取合理保护措施，但无法保证绝对安全。', security2: '对话记录采用 LRU 策略：每个账号最多保留 10 个最近会话，每个会话最多保留 10 条最近消息。', cookieTitle: 'Cookie 与本地存储', cookieText: '平台使用浏览器 localStorage 存储登录凭证（JWT Token）以保持登录，不使用第三方 Cookie 跟踪行为。', rightsTitle: '您的权利', rightsIntro: '您可以随时：', right1: '删除平台内的对话历史。', right2: '在简报中心取消邮件订阅。', right3: '联系我们申请删除账号及相关数据。', contactTitle: '联系我们', contactText: '如有隐私问题，请联系：'
    }
  }
} as const

const deepMerge = (base: any, patch: any): any => Object.fromEntries(
  Object.entries(base).map(([key, value]) => [
    key,
    value && typeof value === 'object' && !Array.isArray(value)
      ? deepMerge(value, patch?.[key] ?? {})
      : patch?.[key] ?? value,
  ]),
)

const zhCN = deepMerge(enUS, overrides) as typeof enUS
export default zhCN
export { zhCN }
