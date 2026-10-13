import { START_LOCATION, createRouter, createWebHistory } from 'vue-router'
import {
  getFeatureGateRedirect,
  getRoutePolicyDecision,
  getSitePageGateRedirect,
  resolveWebsiteCollectionRedirect,
} from '@/features/navigation/routePolicy'
import LayoutView from '@/views/LayoutView.vue'
import { startRouteProgress, stopRouteProgress } from '@/composables/useRouteProgress'

const DashboardView = () => import('@/views/DashboardView.vue')
const GitHubProjectsView = () => import('@/views/GitHubProjectsView.vue')
const RecommendedWebsitesView = () => import('@/views/RecommendedWebsitesView.vue')
const UiLibraryView = () => import('@/views/UiLibraryView.vue')
const ReportView = () => import('@/views/ReportView.vue')
const XBoardView = () => import('@/views/XBoardView.vue')
const MonitorView = () => import('@/views/MonitorView.vue')
const RegisterView = () => import('@/views/RegisterView.vue')
const WeChatLoginView = () => import('@/views/WeChatLoginView.vue')
const OAuthCallbackView = () => import('@/views/OAuthCallbackView.vue')
const OAuthActionCallbackView = () => import('@/views/OAuthActionCallbackView.vue')
const McpOAuthAuthorizeView = () => import('@/views/McpOAuthAuthorizeView.vue')
const PaperReadView = () => import('@/views/PaperReadView.vue')
const DisclaimerView = () => import('@/views/DisclaimerView.vue')
const PrivacyView = () => import('@/views/PrivacyView.vue')
const McpConnectView = () => import('@/views/McpConnectView.vue')
const DshView = () => import('@/views/DshView.vue')
const ContactPageView = () => import('@/views/ContactPageView.vue')
const SubscriptionsView = () => import('@/views/SubscriptionsView.vue')
const NotFoundView = () => import('@/views/NotFoundView.vue')

const router = createRouter({
  history: createWebHistory(),
  routes: [
    // ── 注册 / OAuth 回调（独立全屏，不继承 Layout） ──
    {
      path: '/register',
      name: 'register',
      component: RegisterView,
      meta: { guestOnly: true },
    },
    {
      path: '/oauth/wechat',
      name: 'wechat-login',
      component: WeChatLoginView,
      meta: { guestOnly: true },
    },
    {
      path: '/oauth/callback',
      name: 'oauth-callback',
      component: OAuthCallbackView,
      meta: { guestOnly: true },
    },
    {
      path: '/oauth/action-callback',
      name: 'oauth-action-callback',
      component: OAuthActionCallbackView,
      // 渠道绑定回调须携带当前登录会话：绑定目标 = 当前账户
      meta: { requiresAuth: true },
    },
    {
      // MCP OAuth 授权端点（同意页）。不设 requiresAuth：守卫的登录流程会把首次打开的页面换成首页，
      // 客户端带来的授权请求就丢了，登录由页面自己处理。
      path: '/oauth/authorize',
      name: 'oauth-authorize',
      component: McpOAuthAuthorizeView,
    },

    // ── 主 Layout（大白卡片 + Dock + Auth） ──
    {
      path: '/',
      component: LayoutView,
      children: [
        {
          path: '',
          name: 'dashboard',
          component: DashboardView,
        },
        {
          path: 'projects',
          name: 'github-projects',
          component: GitHubProjectsView,
        },
        {
          path: 'websites',
          name: 'recommended-websites',
          component: RecommendedWebsitesView,
        },
        {
          path: 'ui-library/:id?',
          name: 'ui-library',
          component: UiLibraryView,
        },
        {
          path: 'report',
          name: 'report',
          component: ReportView,
        },
        {
          path: 'subscriptions',
          name: 'subscriptions',
          component: SubscriptionsView,
        // Dock 情报追踪入口；未登录时提示登录并保留目标路径。
          meta: { requiresAuth: true },
        },
        {
          path: 'x',
          name: 'x-board',
          component: XBoardView,
          meta: { feature: 'xSource' },
        },
        {
          path: 'mcp',
          name: 'mcp-connect',
          component: McpConnectView,
          // 获客入口：游客可查看公开 runtime 与客户端选择；登录在向导
          // 「下一步」处由页面内弹窗按需触发，Token API 仍由后端 401 兜底。
        },
        {
          path: 'dsh',
          name: 'dsh',
          component: DshView,
          // 获客入口：游客可查看插件与安装方式；向导「下一步」触发登录后才
          // 由服务端签发账号绑定的 DSH 专用 MCP Token。
        },
        {
          path: 'monitor',
          name: 'monitor',
          component: MonitorView,
          meta: { requiresAdmin: true },
        },
        {
          path: 'papers/:id/read',
          name: 'paper-read',
          component: PaperReadView,
          // 游客只读开放：论文详情 API 本就公开；对话功能由
          // PaperReadView 按登录态降级为引导条。
        },
        {
          path: 'disclaimer',
          name: 'disclaimer',
          component: DisclaimerView,
        },
        {
          path: 'privacy',
          name: 'privacy',
          component: PrivacyView,
        },
        {
          path: 'membership',
          name: 'membership',
          redirect: '/mcp',
        },
        {
          path: 'membership/checkout',
          name: 'membership-checkout',
          redirect: '/mcp',
        },
        {
          path: 'contact',
          name: 'contact',
          component: ContactPageView,
          meta: { sitePage: 'contactPage' },
        },
        // ── 兜底：未知路径（含已下线的 /wechat、/chat 旧书签）显示「页面不存在」，地址原样保留 ──
        // 挂在 Layout 里，报头和 dock 照常可用。/forgot-password 没有路由记录，由全局守卫先行处理，
        // 这里不用路由级 redirect，免得抢在守卫前面。边缘按 public/__routes 的首段清单给未知地址回
        // 404 状态码（页面仍是这份 index.html），新增顶层路由要同步加清单文件，契约见 index.test.ts。
        {
          path: ':pathMatch(.*)*',
          name: 'not-found',
          component: NotFoundView,
        },
      ],
    },
  ],
})

// ── 全局路由守卫 ──────────────────────────────────────────────────────────────
router.beforeEach(async (to, from) => {
  startRouteProgress()
  if (to.path === '/forgot-password') {
    const { useLoginPrompt } = await import('@/composables/useLoginPrompt')
    useLoginPrompt().requestPasswordReset(to.query.redirect)
    return { path: '/', replace: true }
  }
  const { useAuthStore } = await import('@/stores/authStore')
  const { getActivePinia } = await import('pinia')
  const pinia = getActivePinia()
  if (!pinia) return true

  const authStore = useAuthStore(pinia)
  if ((to.meta.requiresAuth || to.meta.requiresAdmin) && authStore.status === 'initializing') {
    await authStore.ensureInitialized()
  }

  const decision = getRoutePolicyDecision(to, authStore)
  if (decision?.kind === 'login') {
    const { useLoginPrompt } = await import('@/composables/useLoginPrompt')
    useLoginPrompt().requestLogin(decision.target)
    return from === START_LOCATION ? { path: '/', replace: true } : false
  }
  if (decision?.kind === 'redirect') return decision.to
  if (decision?.kind === 'block') {
    if (authStore.status === 'degraded') {
      const { useLoginPrompt } = await import('@/composables/useLoginPrompt')
      useLoginPrompt().rememberLoginRedirect(to.fullPath)
    }
    return from === START_LOCATION ? { path: '/', replace: true } : false
  }

  // 网页栏目：游客点「网页」时，站长推荐有内容就先看站长推荐（个人收藏登录后才有）。
  const websiteRedirect = await resolveWebsiteCollectionRedirect(to, authStore,
    async () => (await import('@/composables/recommendedWebsitesSnapshot')).ensureRecommendedWebsites())
  if (websiteRedirect) return websiteRedirect

  // 只在受特性开关保护的路由等待配置；Layout 会异步拉取配置更新导航入口。
  if (to.meta.feature) {
    const { ensureFeatureFlags } = await import('@/composables/useFeatureFlags')
    const featureRedirect = getFeatureGateRedirect(to, await ensureFeatureFlags())
    if (featureRedirect) return featureRedirect
  }

  // 联系合作页仍须在进入前确认开关，其他页面不等待无关配置。
  if (to.meta.sitePage) {
    const { ensureContactPageConfig } = await import('@/composables/useContactPageConfig')
    const sitePageRedirect = getSitePageGateRedirect(to, {
      contactPage: (await ensureContactPageConfig()).enabled,
    })
    if (sitePageRedirect) return sitePageRedirect
  }
  return true
})

// afterEach 对确认与取消（含重定向）的导航都会触发；onError 兜底 chunk 加载失败等异常。
router.afterEach(() => stopRouteProgress())
router.onError(() => stopRouteProgress())

export default router
