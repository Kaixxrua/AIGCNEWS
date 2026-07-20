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

/** 品牌名称 — 从 Vite 环境变量读取，回退默认值 */
const brandName = import.meta.env.VITE_APP_BRAND_NAME || 'AIGC NEWS'

const navItems = [
  {
    to: '/',
    label: 'Dashboard',
    exact: true,
    icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/></svg>`,
  },
  {
    to: '/projects',
    label: 'Projects',
    exact: false,
    icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M4 19.5A2.5 2.5 0 016.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 014 19.5v-15A2.5 2.5 0 016.5 2z"/><path d="M8 7h8"/><path d="M8 11h6"/></svg>`,
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
    to: '/mcp',
    label: 'MCP',
    exact: false,
    icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M7 8a3 3 0 100 6h3"/><path d="M17 8a3 3 0 110 6h-3"/><path d="M8 12h8"/><path d="M12 4v3"/><path d="M12 17v3"/></svg>`,
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

    <!-- ═══ 科技感背景光晕层 ═══ -->
    <div class="bg-glow bg-glow--cyan" />
    <div class="bg-glow bg-glow--violet" />

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
        <router-view v-slot="{ Component }">
          <Transition name="route-fade" mode="out-in">
            <component :is="Component" :key="route.path" class="view-container" />
          </Transition>
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
        :aria-label="item.label"
        :aria-current="isActive(item) ? 'page' : undefined"
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
    <!-- ═══ Dock 中的登录/登出按钮（与导航栏分隔） ═══ -->
    <div class="dock-auth-sep" />
    <!-- 未登录：绿色登录按钮 -->
    <button
      v-if="!authStore.isLoggedIn"
      class="dock-item dock-item--login"
      aria-label="登录账号"
      @click="router.push('/login')"
      @mouseenter="hoveredAuth = true"
      @mouseleave="hoveredAuth = false"
    >
      <span class="dock-icon">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
          <path d="M15 3h4a2 2 0 012 2v14a2 2 0 01-2 2h-4"/>
          <polyline points="10,17 15,12 10,7"/>
          <line x1="15" y1="12" x2="3" y2="12"/>
        </svg>
      </span>
      <Transition name="dock-label">
        <span v-if="hoveredAuth" class="dock-label">登录账号</span>
      </Transition>
    </button>
    <!-- 已登录：红色登出按钮 -->
    <button
      v-else
      class="dock-item dock-item--logout"
      aria-label="退出登录"
      @click="authStore.logout()"
      @mouseenter="hoveredAuth = true"
      @mouseleave="hoveredAuth = false"
    >
      <span class="dock-icon">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
          <path d="M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4"/>
          <polyline points="16,17 21,12 16,7"/>
          <line x1="21" y1="12" x2="9" y2="12"/>
        </svg>
      </span>
      <Transition name="dock-label">
        <span v-if="hoveredAuth" class="dock-label">退出登录</span>
      </Transition>
    </button>
    </nav>

    <!-- ═══ Dock 下方小字（版权 / 免责 / 隐私 / 生态合作） ═══ -->
    <div class="dock-footer">
      <span>Powered by {{ brandName }}</span>
      <span class="footer-sep">·</span>
      <RouterLink to="/disclaimer" class="footer-link">免责声明</RouterLink>
      <span class="footer-sep">·</span>
      <RouterLink to="/privacy" class="footer-link">隐私政策</RouterLink>
      <span class="footer-sep">·</span>
      <RouterLink to="/mcp" class="footer-link">MCP 接入</RouterLink>
      <span class="footer-sep">·</span>
      <span>生态合作联系：<a href="mailto:kaixxrua@gmail.com" class="footer-link">kaixxrua@gmail.com</a></span>
    </div>

  </div>
</template>

<style scoped>
/* ═══ 视图容器：只控制 flex 撑满 + 溢出裁剪 ═══ */
:deep(.view-container) {
  width: 100%;
  height: 100%;
  flex: 1 1 0;
  min-height: 0;
  overflow: hidden;
}

/* ═══ 科技感背景光晕（低透明度，不抢视觉重心） ═══ */
.bg-glow {
  position: fixed;
  border-radius: 50%;
  pointer-events: none;
  z-index: 0;
  filter: blur(100px);
}
.bg-glow--cyan {
  width: 600px;
  height: 600px;
  top: -15%;
  right: -10%;
  background: radial-gradient(circle, rgba(6, 182, 212, 0.06) 0%, transparent 70%);
}
.bg-glow--violet {
  width: 500px;
  height: 500px;
  bottom: -10%;
  left: -5%;
  background: radial-gradient(circle, rgba(139, 92, 246, 0.04) 0%, transparent 70%);
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
  border: 1px solid rgba(168, 162, 158, 0.18);
  box-shadow:
    0 2px 12px rgba(0, 0, 0, 0.03),
    0 0 0 1px rgba(6, 182, 212, 0.04),
    inset 0 1px 0 0 rgba(255, 255, 255, 0.8);
  overflow: hidden;
  display: flex;
  flex-direction: column;
  position: relative;
  z-index: 1;
}

/* ═══ Dock 下方小字（版权 / 免责 / 隐私 / 生态合作） ═══ */
.dock-footer {
  position: fixed;
  bottom: 6px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 99;
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  justify-content: center;
  gap: 0 2px;
  font-size: 10px;
  font-weight: 400;
  color: rgba(168, 162, 158, 0.7);
  letter-spacing: 0.02em;
  white-space: nowrap;
  pointer-events: auto;
  user-select: none;
}

.footer-sep {
  margin: 0 5px;
  opacity: 0.5;
}

.footer-link {
  color: rgba(168, 162, 158, 0.7);
  text-decoration: none;
  transition: color 0.2s;
}

.footer-link:hover {
  color: #78716c;
  text-decoration: underline;
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

/* ═══ Dock 内分隔线 ═══ */
.dock-auth-sep {
  width: 1px;
  height: 20px;
  background: rgba(168, 162, 158, 0.25);
  margin: 0 4px;
  flex-shrink: 0;
}

/* ═══ 登录按钮（绿色调） ═══ */
.dock-item--login {
  color: #16a34a; /* green-600 */
}
.dock-item--login:hover {
  color: #15803d; /* green-700 */
  background: rgba(220, 252, 231, 0.6); /* green-100 */
  transform: scale(1.08);
}

/* ═══ 登出按钮（红色调） ═══ */
.dock-item--logout {
  color: #dc2626; /* red-600 */
}
.dock-item--logout:hover {
  color: #b91c1c; /* red-700 */
  background: rgba(254, 226, 226, 0.6); /* red-100 */
  transform: scale(1.08);
}

@media (max-width: 639px) {
  .main-canvas {
    width: 100%;
    height: 100dvh;
    min-height: 100dvh;
    border-radius: 18px;
  }

  .main-canvas > .absolute.top-0 {
    padding-left: max(12px, env(safe-area-inset-left));
    padding-right: max(12px, env(safe-area-inset-right));
  }

  .main-canvas > .absolute.inset-0 {
    padding-top: 48px;
    padding-bottom: 86px;
  }

  .dock {
    left: 8px;
    right: 8px;
    bottom: max(8px, env(safe-area-inset-bottom));
    transform: none;
    max-width: calc(100vw - 16px);
    overflow-x: auto;
    justify-content: flex-start;
    gap: 4px;
    padding: 6px 8px;
    scrollbar-width: none;
  }

  .dock::-webkit-scrollbar { display: none; }
  .dock-item { flex: 0 0 44px; }
  .dock-label { display: none; }
  .dock-auth-sep { margin: 0 2px; }

  .dock-footer {
    left: 12px;
    right: 12px;
    bottom: calc(66px + env(safe-area-inset-bottom));
    transform: none;
    max-width: calc(100vw - 24px);
    line-height: 1.5;
    white-space: normal;
    text-align: center;
    overflow-wrap: anywhere;
  }
}

@media (prefers-reduced-motion: reduce) {
  .dock-item,
  .dock-label-enter-active,
  .dock-label-leave-active { transition: none; }
}
</style>
