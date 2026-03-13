import { createRouter, createWebHistory } from 'vue-router'
import DashboardView from '../views/DashboardView.vue'
import ChatView from '../views/ChatView.vue'
import ReportView from '../views/ReportView.vue'
import MonitorView from '../views/MonitorView.vue'

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
    },
    {
      path: '/report',
      name: 'report',
      component: ReportView,
    },
    {
      path: '/monitor',
      name: 'monitor',
      component: MonitorView,
    },
  ],
})

export default router
