import { createRouter, createWebHistory } from 'vue-router'
import LayoutView from '../views/LayoutView.vue'
import DashboardView from '../views/DashboardView.vue'
import GitHubProjectsView from '../views/GitHubProjectsView.vue'
import ChatView from '../views/ChatView.vue'
import ReportView from '../views/ReportView.vue'
import MonitorView from '../views/MonitorView.vue'
import LoginView from '../views/LoginView.vue'
import RegisterView from '../views/RegisterView.vue'
import PaperReadView from '../views/PaperReadView.vue'
import DisclaimerView from '../views/DisclaimerView.vue'
import PrivacyView from '../views/PrivacyView.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    // ── 登录 / 注册（独立全屏，不继承 Layout） ──
    {
      path: '/login',
      name: 'login',
      component: LoginView,
      meta: { guestOnly: true },
    },
    {
      path: '/register',
      name: 'register',
      component: RegisterView,
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
  const { useAuthStore } = await import('../stores/authStore')
  const { getActivePinia } = await import('pinia')
  const pinia = getActivePinia()
  if (!pinia) { next(); return }

  const authStore = useAuthStore(pinia)

  if (to.meta.requiresAuth && !authStore.isLoggedIn) {
    next({ path: '/login', query: { redirect: to.fullPath } })
    return
  }

  if (to.meta.requiresAdmin && !authStore.isAdmin) {
    next({ path: '/' })
    return
  }

  if (to.meta.guestOnly && authStore.isLoggedIn) {
    next({ path: '/' })
    return
  }

  next()
})

export default router
