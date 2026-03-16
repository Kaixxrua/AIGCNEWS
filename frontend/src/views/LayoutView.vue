<script setup lang="ts">
import { ref } from 'vue'
import { RouterLink, RouterView, useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '../stores/authStore'
import GlobalSearch from '../components/GlobalSearch.vue'

const route = useRoute()
const router = useRouter()
const hoveredNav = ref<string | null>(null)
const hoveredAuth = ref(false)
const authStore = useAuthStore()

const handleAuthAction = () => {
  if (authStore.isLoggedIn) {
    authStore.logout()
  } else {
    router.push('/login')
  }
}

const navItems = [
  {
    to: '/',
    label: 'Dashboard',
    exact: true,
    icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/></svg>`,
  },
  {
    to: '/chat',
    label: 'Chat',
    exact: false,
    icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"/></svg>`,
  },
  {
    to: '/report',
    label: 'Report',
    exact: false,
    icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14,2 14,8 20,8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>`,
  },
  {
    to: '/monitor',
    label: 'Monitor',
    exact: false,
    requiresAdmin: true,
    icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><polyline points="22,12 18,12 15,21 9,3 6,12 2,12"/></svg>`,
  },
]

const isActive = (item: { to: string; exact: boolean }) => {
  if (item.exact) return route.path === item.to
  return route.path.startsWith(item.to)
}
</script>

<template>
  <!-- ═══ 全屏内容层 ═══ -->
  <div class="relative flex h-screen w-full items-center justify-center overflow-hidden">

    <!-- ═══ 居中悬浮画板（暖白纸质毛玻璃主面板） ═══ -->
    <div class="main-canvas">
      <!-- 顶部全局搜索条 -->
      <div
        class="absolute top-0 left-0 right-0 flex items-center justify-center px-6 py-2.5 shrink-0"
        style="z-index: 100; border-bottom: 1px solid rgba(168,162,158,0.12); background: rgba(255,255,255,0.75); backdrop-filter: blur(8px);"
      >
        <GlobalSearch />
      </div>

      <!-- 内容区（搜索条占位 44px） -->
      <div class="absolute inset-0 pt-[44px] flex flex-col">
        <router-view v-slot="{ Component }" class="router-view-shell">
          <component :is="Component" class="view-container" />
        </router-view>
      </div>
    </div>

    <!-- ═══ 底部悬浮 Dock 导航栏（暖白纸质） ═══ -->
    <nav class="dock">
      <RouterLink
        v-for="item in navItems"
        :key="item.to"
        :to="item.to"
        v-show="!item.requiresAdmin || authStore.isAdmin"
        class="dock-item"
        :class="{ 'dock-item--active': isActive(item) }"
        @mouseenter="hoveredNav = item.to"
        @mouseleave="hoveredNav = null"
      >
        <span class="dock-icon" v-html="item.icon" />
        <Transition name="dock-label">
          <span
            v-if="hoveredNav === item.to"
            class="dock-label"
          >
            {{ item.label }}
          </span>
        </Transition>
      </RouterLink>
    </nav>

    <!-- ═══ 右上角独立 Auth 浮岛 ═══ -->
    <div class="auth-island">
      <button
        class="dock-item"
        :class="{ 'dock-item--auth-active': authStore.isLoggedIn }"
        @click="handleAuthAction"
        @mouseenter="hoveredAuth = true"
        @mouseleave="hoveredAuth = false"
      >
        <!-- 已登录：离开图标 -->
        <span v-if="authStore.isLoggedIn" class="dock-icon">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
            <path d="M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4"/>
            <polyline points="16,17 21,12 16,7"/>
            <line x1="21" y1="12" x2="9" y2="12"/>
          </svg>
        </span>
        <!-- 未登录：进入图标 -->
        <span v-else class="dock-icon">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
            <path d="M15 3h4a2 2 0 012 2v14a2 2 0 01-2 2h-4"/>
            <polyline points="10,17 15,12 10,7"/>
            <line x1="15" y1="12" x2="3" y2="12"/>
          </svg>
        </span>
        <!-- Tooltip -->
        <Transition name="dock-label">
          <span v-if="hoveredAuth" class="dock-label">
            {{ authStore.isLoggedIn ? '退出登录' : '登录账号' }}
          </span>
        </Transition>
      </button>
    </div>

  </div>
</template>

<style scoped>
/* ═══ 视图容器：只控制 flex 撑满 + 溢出裁剪，不强制 flex-direction ═══ */
:deep(.view-container) {
  width: 100%;
  height: 100%;
  flex: 1 1 0;
  min-height: 0;
  overflow: hidden;
}

/* ═══ 主悬浮画板（暖白纸质毛玻璃） ═══ */
.main-canvas {
  width: 92%;
  max-width: 1400px;
  height: 84vh;
  border-radius: 32px;
  background: rgba(255, 255, 255, 0.85);
  backdrop-filter: blur(32px) saturate(180%);
  -webkit-backdrop-filter: blur(32px) saturate(180%);
  border: 1px solid rgba(168, 162, 158, 0.20);
  box-shadow:
    0 2px 12px rgba(0, 0, 0, 0.03),
    inset 0 1px 0 0 rgba(255, 255, 255, 0.8);
  overflow: hidden;
  display: flex;
  flex-direction: column;
  position: relative;
}

/* ═══ 底部 Dock（暖白纸质） ═══ */
.dock {
  position: fixed;
  bottom: 28px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 100;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 24px;
  background: rgba(255, 255, 255, 0.85);
  backdrop-filter: blur(24px) saturate(180%);
  -webkit-backdrop-filter: blur(24px) saturate(180%);
  border: 1px solid rgba(168, 162, 158, 0.20);
  border-radius: 999px;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.04);
}

.dock-item {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 44px;
  height: 44px;
  border-radius: 50%;
  transition: all 0.25s cubic-bezier(0.25, 0.8, 0.25, 1);
  color: #a8a29e; /* stone-400 */
  text-decoration: none;
  background: transparent;
  border: none;
  cursor: pointer;
}

.dock-item:hover {
  color: #57534e; /* stone-600 */
  background: rgba(245, 245, 244, 0.8); /* stone-100 */
  transform: scale(1.08);
}

.dock-item--active {
  color: #44403c; /* stone-700 */
  background: #f5f5f4; /* stone-100 */
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.06);
}

.dock-item--active:hover {
  color: #44403c;
  background: #e7e5e4; /* stone-200 */
  transform: scale(1.08);
}

.dock-icon {
  width: 20px;
  height: 20px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.dock-icon svg {
  width: 20px;
  height: 20px;
}

/* Dock 悬浮标签（tooltip — 暖色） */
.dock-label {
  position: absolute;
  bottom: calc(100% + 10px);
  left: 50%;
  transform: translateX(-50%);
  white-space: nowrap;
  font-size: 11px;
  font-weight: 600;
  color: #44403c; /* stone-700 */
  background: rgba(255, 255, 255, 0.90);
  backdrop-filter: blur(10px);
  padding: 4px 12px;
  border-radius: 999px;
  border: 1px solid rgba(168, 162, 158, 0.15);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.05);
  pointer-events: none;
}

.dock-label-enter-active,
.dock-label-leave-active {
  transition: all 0.2s cubic-bezier(0.25, 0.8, 0.25, 1);
}
.dock-label-enter-from,
.dock-label-leave-to {
  opacity: 0;
  transform: translateX(-50%) translateY(4px) scale(0.9);
}
.dock-label-enter-to,
.dock-label-leave-from {
  opacity: 1;
  transform: translateX(-50%) translateY(0) scale(1);
}

/* ═══ 路由切换：无缝交叉空间缩放 ═══ */
.spatial-fade-enter-active,
.spatial-fade-leave-active {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  width: 100%;
  height: 100%;
  transition: opacity 0.6s ease,
              transform 0.6s cubic-bezier(0.22, 1, 0.36, 1),
              filter 0.6s ease;
  will-change: transform, opacity, filter;
}

.spatial-fade-enter-from {
  opacity: 0;
  transform: scale(0.95);
  filter: blur(10px);
}

.spatial-fade-leave-to {
  opacity: 0;
  transform: scale(1.05);
  filter: blur(10px);
  z-index: 10;
}

/* ═══ 右上角独立 Auth 浮岛 ═══ */
.auth-island {
  position: fixed;
  top: 28px;
  right: 28px;
  z-index: 100;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 10px;
  background: rgba(255, 255, 255, 0.85);
  backdrop-filter: blur(24px) saturate(180%);
  -webkit-backdrop-filter: blur(24px) saturate(180%);
  border: 1px solid rgba(168, 162, 158, 0.20);
  border-radius: 999px;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.04);
}
</style>
