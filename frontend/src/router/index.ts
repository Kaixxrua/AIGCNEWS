import { createRouter, createWebHistory } from 'vue-router'
import {
  getFeatureGateRedirect,
  getRoutePolicyRedirect,
  getSitePageGateRedirect,
} from '@/features/navigation/routePolicy'
import LayoutView from '@/views/LayoutView.vue'
import { startRouteProgress, stopRouteProgress } from '@/composables/useRouteProgress'

const DashboardView = () => import('@/views/DashboardView.vue')
const GitHubProjectsView = () => import('@/views/GitHubProjectsView.vue')
const ChatView = () => import('@/views/ChatView.vue')
const ReportView = () => import('@/views/ReportView.vue')
const XBoardView = () => import('@/views/XBoardView.vue')
const WechatView = () => import('@/views/WechatView.vue')
const MonitorView = () => import('@/views/MonitorView.vue')
const LoginView = () => import('@/views/LoginView.vue')
const RegisterView = () => import('@/views/RegisterView.vue')
const ForgotPasswordView = () => import('@/views/ForgotPasswordView.vue')
const OAuthCallbackView = () => import('@/views/OAuthCallbackView.vue')
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
    // ── 登录 / 注册（独立全屏，不继承 Layout） ──
    {
      path: '/login',
      name: 'login',
      component: LoginView,
    },
    {
      path: '/register',
      name: 'register',
      component: RegisterView,
      meta: { guestOnly: true },
    },
    {
      path: '/forgot-password',
      name: 'forgot-password',
      component: ForgotPasswordView,
      meta: { guestOnly: true },
    },
    {
      path: '/oauth/callback',
      name: 'oauth-callback',
      component: OAuthCallbackView,
      meta: { guestOnly: true },
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
          // 复杂渠道与单条 Push 订阅管理兼容深链；主 Dock 不展示该入口。
          meta: { requiresAuth: true },
        },
        {
          path: 'x',
          name: 'x-board',
          component: XBoardView,
          meta: { feature: 'xSource' },
        },
        {
          path: 'wechat',
          name: 'wechat',
          component: WechatView,
          meta: { requiresAdmin: true, feature: 'wechatSource' },
        },
        {
          path: 'mcp',
          name: 'mcp-connect',
          component: McpConnectView,
          // MCP 配置页只负责登录后的客户端与 Token 管理；运行时仍允许站外匿名调用
          meta: { requiresAuth: true },
        },
        {
          path: 'dsh',
          name: 'dsh',
          component: DshView,
          // DSH 向导自动签发账号绑定的 MCP Token：游客必须登录
          meta: { requiresAuth: true },
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
router.beforeEach(async (to, _from, next) => {
  startRouteProgress()
  const { useAuthStore } = await import('@/stores/authStore')
  const { getActivePinia } = await import('pinia')
  const pinia = getActivePinia()
  if (!pinia) { next(); return }

  const authStore = useAuthStore(pinia)
  const redirect = getRoutePolicyRedirect(to, authStore)

  if (redirect) return next(redirect)

  // 可插拔源特性门控：开关关闭时源路由回首页（开关进程内缓存，仅首次拉取）
  const { ensureFeatureFlags } = await import('@/composables/useFeatureFlags')
  const featureRedirect = getFeatureGateRedirect(to, await ensureFeatureFlags())
  if (featureRedirect) return next(featureRedirect)

  // 站点页面门控：联系合作页未启用时回首页（配置进程内缓存，仅首次拉取）
  const { ensureContactPageConfig } = await import('@/composables/useContactPageConfig')
  const sitePageRedirect = getSitePageGateRedirect(to, {
    contactPage: (await ensureContactPageConfig()).enabled,
  })
  if (sitePageRedirect) return next(sitePageRedirect)
  next()
})

// afterEach 对确认与取消（含重定向）的导航都会触发；onError 兜底 chunk 加载失败等异常。
router.afterEach(() => stopRouteProgress())
router.onError(() => stopRouteProgress())

export default router
