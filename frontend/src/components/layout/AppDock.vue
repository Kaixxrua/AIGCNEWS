<script setup lang="ts">
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { isNavigationItemActive, type NavigationItem } from '@/features/navigation/navigationModel'

const props = defineProps<{
  items: readonly NavigationItem[]
  currentPath: string
  isAdmin: boolean
  isLoggedIn: boolean
}>()

const emit = defineEmits<{
  login: []
  logout: []
}>()

const { t } = useI18n()
const hoveredNav = ref<string | null>(null)
const hoveredAuth = ref(false)
</script>

<template>
  <!-- ═══ 底部悬浮 Dock 导航栏（暖白纸质） ═══ -->
  <nav class="dock">
    <RouterLink
      v-for="item in props.items"
      :key="item.to"
      :to="item.to"
      v-show="!item.requiresAdmin || props.isAdmin"
      :aria-label="t(item.labelKey)"
      :aria-current="isNavigationItemActive(item, props.currentPath) ? 'page' : undefined"
      class="dock-item"
      :class="{ 'dock-item--active': isNavigationItemActive(item, props.currentPath) }"
      @mouseenter="hoveredNav = item.to"
      @mouseleave="hoveredNav = null"
    >
      <span class="dock-icon" v-html="item.icon" />
      <Transition name="dock-label">
        <span v-if="hoveredNav === item.to" class="dock-label">
          {{ t(item.labelKey) }}
        </span>
      </Transition>
    </RouterLink>
    <!-- ═══ Dock 中的登录/登出按钮（与导航栏分隔） ═══ -->
    <div class="dock-auth-sep" />
    <!-- 未登录：绿色登录按钮 -->
    <button
      v-if="!props.isLoggedIn"
      class="dock-item dock-item--login"
      :aria-label="t('navigation.loginAccount')"
      @click="emit('login')"
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
        <span v-if="hoveredAuth" class="dock-label">{{ t('navigation.loginAccount') }}</span>
      </Transition>
    </button>
    <!-- 已登录：红色登出按钮 -->
    <button
      v-else
      class="dock-item dock-item--logout"
      :aria-label="t('navigation.logout')"
      @click="emit('logout')"
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
        <span v-if="hoveredAuth" class="dock-label">{{ t('navigation.logout') }}</span>
      </Transition>
    </button>
  </nav>
</template>

<style scoped>
.dock {
  position: fixed;
  bottom: 28px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 100;
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 7px 10px;
  background: var(--paper-raised);
  border: 1px solid var(--rule-strong);
  border-radius: 10px;
  box-shadow: 4px 4px 0 var(--ink);
}

.dock-item {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 44px;
  height: 44px;
  border-radius: 6px;
  transition: all 0.16s ease;
  color: var(--ink-muted);
  text-decoration: none;
  background: transparent;
  border: none;
  cursor: pointer;
}

.dock-item:hover {
  color: var(--ink);
  background: var(--acid-soft);
  transform: translateY(-2px);
}

.dock-item--active {
  color: var(--acid-ink);
  background: var(--acid);
  box-shadow: inset 0 -3px 0 var(--ink);
}

.dock-item--active:hover {
  color: var(--acid-ink);
  background: var(--acid);
  transform: translateY(-2px);
}

.dock-icon {
  width: 20px;
  height: 20px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.dock-icon :deep(svg) {
  width: 20px;
  height: 20px;
}

.dock-label {
  position: absolute;
  bottom: calc(100% + 10px);
  left: 50%;
  transform: translateX(-50%);
  white-space: nowrap;
  font-size: 11px;
  font-weight: 600;
  color: var(--acid);
  background: var(--ink);
  padding: 4px 10px;
  border-radius: 5px;
  border: 1px solid var(--ink);
  box-shadow: 2px 2px 0 var(--acid);
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

.dock-auth-sep {
  width: 1px;
  height: 20px;
  background: var(--rule-strong);
  margin: 0 4px;
  flex-shrink: 0;
}

.dock-item--login { color: var(--acid-ink); background: var(--acid); }
.dock-item--login:hover {
  color: var(--acid);
  background: var(--ink);
  transform: translateY(-2px);
}

.dock-item--logout { color: #dc2626; }
.dock-item--logout:hover {
  color: #b91c1c;
  background: rgba(254, 226, 226, 0.6);
  transform: translateY(-2px);
}

@media (max-width: 639px) {
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
}

@media (prefers-reduced-motion: reduce) {
  .dock-item,
  .dock-label-enter-active,
  .dock-label-leave-active { transition: none; }
}
</style>
