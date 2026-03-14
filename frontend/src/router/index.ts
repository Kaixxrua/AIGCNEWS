import { createRouter, createWebHistory } from 'vue-router'
import DashboardView from '../views/DashboardView.vue'
import ChatView from '../views/ChatView.vue'
import ReportView from '../views/ReportView.vue'
import MonitorView from '../views/MonitorView.vue'
import LoginView from '../views/LoginView.vue'
import RegisterView from '../views/RegisterView.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      name: 'dashboard',
      component: DashboardView,
    },
    {
      path: '/chat',
      name: 'chat',
      component: ChatView,
      // chat 页不强制跳转，未登录时显示遮罩（柔性降级）
    },
    {
      path: '/report',
      name: 'report',
      component: ReportView,
      // report 页面完全开放，未登录用户可阅读历史报告，Admin 才能生成报告
    },
    {
      path: '/monitor',
      name: 'monitor',
      component: MonitorView,
      meta: { requiresAdmin: true },
    },
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
  ],
})

// ── 全局路由守卫 ──────────────────────────────────────────────────────────────
router.beforeEach(async (to, _from, next) => {
  // 延迟导入避免循环依赖
  const { useAuthStore } = await import('../stores/authStore')
  const { getActivePinia } = await import('pinia')
  const pinia = getActivePinia()
  if (!pinia) { next(); return }

  const authStore = useAuthStore(pinia)

  // 需要登录的路由：未登录时重定向到 /login，并记录来源
  if (to.meta.requiresAuth && !authStore.isLoggedIn) {
    next({ path: '/login', query: { redirect: to.fullPath } })
    return
  }

  // 需要 admin 的路由：非 admin 重定向到 /
  if (to.meta.requiresAdmin && !authStore.isAdmin) {
    next({ path: '/' })
    return
  }

  // 已登录时访问 guest-only 页面（/login, /register）→ 跳转到首页
  if (to.meta.guestOnly && authStore.isLoggedIn) {
    next({ path: '/' })
    return
  }

  next()
})

export default router
