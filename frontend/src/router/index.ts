import { createRouter, createWebHistory } from 'vue-router'
import { getRoutePolicyRedirect } from '@/features/navigation/routePolicy'
import LayoutView from '@/views/LayoutView.vue'

const DashboardView = () => import('@/views/DashboardView.vue')
const GitHubProjectsView = () => import('@/views/GitHubProjectsView.vue')
const ChatView = () => import('@/views/ChatView.vue')
const ReportView = () => import('@/views/ReportView.vue')
const MonitorView = () => import('@/views/MonitorView.vue')
const LoginView = () => import('@/views/LoginView.vue')
const RegisterView = () => import('@/views/RegisterView.vue')
const ForgotPasswordView = () => import('@/views/ForgotPasswordView.vue')
const PaperReadView = () => import('@/views/PaperReadView.vue')
const DisclaimerView = () => import('@/views/DisclaimerView.vue')
const PrivacyView = () => import('@/views/PrivacyView.vue')
const McpConnectView = () => import('@/views/McpConnectView.vue')

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
        },
        {
          path: 'report',
          name: 'report',
          component: ReportView,
        },
        {
          path: 'mcp',
          name: 'mcp-connect',
          component: McpConnectView,
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
          meta: { requiresAuth: true },
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
      ],
    },
  ],
})

// ── 全局路由守卫 ──────────────────────────────────────────────────────────────
router.beforeEach(async (to, _from, next) => {
  const { useAuthStore } = await import('@/stores/authStore')
  const { getActivePinia } = await import('pinia')
  const pinia = getActivePinia()
  if (!pinia) { next(); return }

  const authStore = useAuthStore(pinia)
  const redirect = getRoutePolicyRedirect(to, authStore)

  if (redirect) return next(redirect)
  next()
})

export default router
