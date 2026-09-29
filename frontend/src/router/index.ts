import { START_LOCATION, createRouter, createWebHistory } from 'vue-router'
import {
  getFeatureGateRedirect,
  getRoutePolicyDecision,
  getSitePageGateRedirect,
} from '@/features/navigation/routePolicy'
import LayoutView from '@/views/LayoutView.vue'
import { startRouteProgress, stopRouteProgress } from '@/composables/useRouteProgress'

const DashboardView = () => import('@/views/DashboardView.vue')
const GitHubProjectsView = () => import('@/views/GitHubProjectsView.vue')
const RecommendedWebsitesView = () => import('@/views/RecommendedWebsitesView.vue')
const UiLibraryView = () => import('@/views/UiLibraryView.vue')
const ChatView = () => import('@/views/ChatView.vue')
const ReportView = () => import('@/views/ReportView.vue')
const XBoardView = () => import('@/views/XBoardView.vue')
const MonitorView = () => import('@/views/MonitorView.vue')
const RegisterView = () => import('@/views/RegisterView.vue')
const OAuthCallbackView = () => import('@/views/OAuthCallbackView.vue')
const OAuthActionCallbackView = () => import('@/views/OAuthActionCallbackView.vue')
const PaperReadView = () => import('@/views/PaperReadView.vue')
const DisclaimerView = () => import('@/views/DisclaimerView.vue')
const PrivacyView = () => import('@/views/PrivacyView.vue')
const McpConnectView = () => import('@/views/McpConnectView.vue')
const DshView = () => import('@/views/DshView.vue')
const ContactPageView = () => import('@/views/ContactPageView.vue')
const MembershipView = () => import('@/views/MembershipView.vue')
const MembershipCheckoutView = () => import('@/views/MembershipCheckoutView.vue')
const SubscriptionsView = () => import('@/views/SubscriptionsView.vue')

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
          path: 'chat',
          name: 'chat',
          component: ChatView,
          meta: { requiresAdmin: true },
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
          component: MembershipView,
          // 游客可见：会员页本身是获客入口，不做登录门控
        },
        {
          path: 'membership/checkout',
          name: 'membership-checkout',
          component: MembershipCheckoutView,
          // 下单须登录（支付开关关闭时会员页不会给出入口，直达也由
          // 后端 gate 404 兜底）
          meta: { requiresAuth: true },
        },
        {
          path: 'contact',
          name: 'contact',
          component: ContactPageView,
          meta: { sitePage: 'contactPage' },
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

  // 可插拔源特性门控：开关关闭时源路由回首页（开关进程内缓存，仅首次拉取）
  const { ensureFeatureFlags } = await import('@/composables/useFeatureFlags')
  const featureRedirect = getFeatureGateRedirect(to, await ensureFeatureFlags())
  if (featureRedirect) return featureRedirect

  // 站点页面门控：联系合作页未启用时回首页（配置进程内缓存，仅首次拉取）
  const { ensureContactPageConfig } = await import('@/composables/useContactPageConfig')
  const sitePageRedirect = getSitePageGateRedirect(to, {
    contactPage: (await ensureContactPageConfig()).enabled,
  })
  return sitePageRedirect ?? true
})

// afterEach 对确认与取消（含重定向）的导航都会触发；onError 兜底 chunk 加载失败等异常。
router.afterEach(() => stopRouteProgress())
router.onError(() => stopRouteProgress())

export default router
