<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useMediaQuery } from '@vueuse/core'
import MobileNavigation from './MobileNavigation.vue'
import { useI18n } from 'vue-i18n'
import { LogIn, LogOut, MoreHorizontal, UserRound, X } from 'lucide-vue-next'
import { isNavigationItemActive, type NavigationItem } from '@/features/navigation/navigationModel'
import LayoutFooter from './LayoutFooter.vue'

const props = withDefaults(defineProps<{
  items: readonly NavigationItem[]
  currentPath: string
  currentQuery?: Readonly<Record<string, unknown>>
  isAdmin: boolean
  isLoggedIn: boolean
  alertItems?: readonly string[]
  brandName?: string
}>(), { brandName: 'AIGC NEWS' })

const emit = defineEmits<{ login: []; logout: []; accountSettings: [] }>()
const { t } = useI18n()
const alertLabel = (path: string) => t(path === '/subscriptions' ? 'tracking.unread' : 'navigation.monitorAlert')
const isMobile = useMediaQuery('(max-width: 767px)')
const primaryPaths = new Set(['/', '/projects', '/report', '/subscriptions'])
const visibleItems = computed(() => props.items.filter(item =>
  (!item.requiresAdmin || props.isAdmin) && (!item.requiresAuth || props.isLoggedIn),
))
const moreItems = computed(() => visibleItems.value.filter(item => !primaryPaths.has(item.to)))
const moreActive = computed(() => moreItems.value.some(item => isActive(item)))
const moreAlert = computed(() => moreItems.value.some(item => props.alertItems?.includes(item.to)))
const moreDialog = ref<HTMLDialogElement | null>(null)
const moreOpen = ref(false)
const isActive = (item: NavigationItem) => isNavigationItemActive(item, props.currentPath, props.currentQuery)
const label = (item: NavigationItem) => item.labelText || t(item.labelKey)
// Compact Chinese captions are intentionally visible in either interface locale.
const captions: Record<string, string> = {
  '/': '首页', '/projects': '项目库', '/ui-library': 'UI库', '/projects?source=website': '网页',
  '/chat': '对话', '/report': '简报', '/x': 'X动态', '/wechat': '微信', '/mcp': 'MCP', '/dsh': 'DSH',
  '/subscriptions': '情报追踪', '/membership': '会员', '/contact': '联系我们', '/monitor': '监控',
}
const caption = (item: NavigationItem) => captions[item.to] || label(item)



function openMore() {
  moreDialog.value?.showModal()
  moreOpen.value = true
}
function closeMore() {
  if (moreDialog.value?.open) moreDialog.value.close()
  moreOpen.value = false
}
function account() {
  closeMore()
  if (props.isLoggedIn) emit('accountSettings')
  else emit('login')
}
function logout() {
  closeMore()
  emit('logout')
}
function dismissBackdrop(event: MouseEvent) {
  if (event.target !== moreDialog.value) return
  const rect = moreDialog.value?.getBoundingClientRect()
  if (rect && (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom)) closeMore()
}
watch(() => [props.currentPath, props.currentQuery], closeMore)
</script>

<template>
  <div class="app-dock-host">
    <MobileNavigation v-if="isMobile" v-bind="props" @login="emit('login')" @logout="emit('logout')" @account-settings="emit('accountSettings')" />
    <template v-else>
  <nav class="dock" :aria-label="t('navigation.primary')">
    <RouterLink
      v-for="item in visibleItems" :key="item.to" :to="item.to"
      :aria-label="props.alertItems?.includes(item.to) ? label(item) + '，' + alertLabel(item.to) : label(item)" :title="label(item)"
      :aria-current="isActive(item) ? 'page' : undefined"
      class="dock-item"
      :class="{ 'dock-item--wide': caption(item).length > 3, 'dock-item--active': isActive(item), 'dock-item--secondary': !primaryPaths.has(item.to) }"
    >
      <span class="dock-icon" aria-hidden="true" v-html="item.icon" />
      <span v-if="props.alertItems?.includes(item.to)" class="dock-alert-dot" :aria-label="alertLabel(item.to)" />
      <span class="dock-label">{{ caption(item) }}</span>
    </RouterLink>
    <div class="dock-auth-sep" aria-hidden="true" />
    <button class="dock-item dock-item--account" :aria-label="t(isLoggedIn ? 'navigation.accountSettings' : 'navigation.loginAccount')" :title="t(isLoggedIn ? 'navigation.accountSettings' : 'navigation.loginAccount')" @click="account">
      <UserRound v-if="isLoggedIn" class="dock-icon" aria-hidden="true" />
      <LogIn v-else class="dock-icon" aria-hidden="true" />
      <span class="dock-label">{{ isLoggedIn ? '账户' : '登录' }}</span>
    </button>
    <button v-if="isLoggedIn" class="dock-item dock-item--secondary dock-item--logout" :aria-label="t('navigation.logout')" @click="logout">
      <LogOut class="dock-icon" aria-hidden="true" />
      <span class="dock-label">退出</span>
    </button>
    <button class="dock-item dock-item--more" :class="{ 'dock-item--active': moreActive }" :aria-label="t('navigation.more')" aria-haspopup="dialog" aria-controls="dock-more-menu" :aria-expanded="moreOpen" @click="openMore">
      <MoreHorizontal class="dock-icon" aria-hidden="true" />
      <span v-if="moreAlert" class="dock-alert-dot" :aria-label="t('navigation.monitorAlert')" />
      <span class="dock-label">更多</span>
    </button>
  </nav>

  <dialog id="dock-more-menu" ref="moreDialog" class="dock-more" aria-labelledby="dock-more-title" @click="dismissBackdrop" @close="moreOpen = false" @cancel="moreOpen = false">
    <header class="dock-more__header">
      <h2 id="dock-more-title">{{ t('navigation.more') }}</h2>
      <button class="dock-more__close" :aria-label="t('common.close')" autofocus @click="closeMore"><X :size="20" aria-hidden="true" /></button>
    </header>
    <nav class="dock-more__links" :aria-label="t('navigation.more')">
      <RouterLink v-for="item in moreItems" :key="item.to" :to="item.to" :aria-current="isActive(item) ? 'page' : undefined" class="dock-more__link" @click="closeMore">
        <span class="dock-icon" aria-hidden="true" v-html="item.icon" />
        <span>{{ label(item) }}</span>
        <span v-if="props.alertItems?.includes(item.to)" class="dock-alert-dot" :aria-label="alertLabel(item.to)" />
      </RouterLink>
    </nav>
    <button v-if="isLoggedIn" class="dock-more__signout" @click="logout"><LogOut :size="16" aria-hidden="true" />{{ t('auth.logout') }}</button>
    <LayoutFooter :brand-name="brandName" embedded @click="closeMore" />
  </dialog>
    </template>
  </div>
</template>

<style scoped>
.dock {
  position: fixed;
  bottom: 36px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 100;
  display: flex;
  align-items: center;
  gap: 6px;
  max-width: calc(100vw - 48px);
  padding: 8px;
  border: 1px solid var(--dock-edge);
  border-radius: 18px;
  background: var(--dock-surface);
  box-shadow: 0 8px 24px rgb(17 25 10 / .2), inset 0 1px 0 rgb(255 255 255 / .08);
}
.dock-item {
  position: relative;
  display: flex;
  flex: 0 0 44px;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 4px;
  width: 44px;
  min-width: 44px;
  height: 44px;
  padding: 4px;
  border: 0;
  border-radius: 11px;
  color: var(--dock-text);
  background: transparent;
  text-decoration: none;
  cursor: pointer;
  transition: color 160ms ease, background 160ms ease, transform 160ms ease;
}
.dock-item:hover { color: var(--acid); background: var(--dock-hover); transform: translateY(-3px); }
.dock-item--active, .dock-item--active:hover { color: var(--acid-ink); background: var(--acid); }
.dock-icon { display: inline-flex; width: 20px; height: 20px; flex: 0 0 20px; align-items: center; justify-content: center; }
.dock-icon :deep(svg) { width: 20px; height: 20px; }
.dock-label { position: absolute; bottom: calc(100% + 16px); left: 50%; transform: translate(-50%, 4px); width: max-content; max-width: 180px; padding: 6px 10px; border: 1px solid var(--dock-edge); border-radius: 6px; color: var(--acid); background: var(--dock-surface); box-shadow: 2px 2px 0 var(--acid); font-size: 12px; line-height: 1.4; font-weight: 650; white-space: nowrap; opacity: 0; visibility: hidden; pointer-events: none; transition: opacity 140ms ease, transform 140ms ease; }
.dock-item:hover .dock-label, .dock-item:focus-visible .dock-label { opacity: 1; visibility: visible; transform: translate(-50%, 0); }
.dock-item:focus-visible { outline: 2px solid var(--acid); outline-offset: 3px; }
.dock-auth-sep { width: 1px; height: 24px; margin: 0 3px; background: var(--dock-edge); flex-shrink: 0; }
.dock-item--account { color: var(--acid); }
.dock-item--logout { color: var(--danger); }
.dock-item--more { display: none; }
.dock-alert-dot { position: absolute; top: 6px; right: 12px; width: 7px; height: 7px; border: 1px solid var(--paper-raised); border-radius: 50%; background: var(--error-accent); }
.dock-more { position: fixed; inset: auto 12px 12px; width: min(480px, calc(100vw - 24px)); max-height: calc(100dvh - 32px); margin: 0 auto; padding: 20px; border: 1px solid var(--rule); border-radius: 16px; background: var(--paper-raised); color: var(--ink); box-shadow: var(--surface-shadow-raised); overscroll-behavior: contain; }
.dock-more::backdrop { background: rgb(0 0 0 / .35); }
.dock-more__header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 16px; }
.dock-more__header h2 { font-size: 20px; font-weight: 750; }
.dock-more__close { display: grid; place-items: center; width: 44px; height: 44px; border-radius: var(--control-radius); background: var(--paper-muted); }
.dock-more__links { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
.dock-more__link { position: relative; display: flex; align-items: center; gap: 12px; min-height: 56px; padding: 12px; border: 1px solid var(--rule); border-radius: var(--control-radius); font-size: 14px; overflow-wrap: anywhere; }
.dock-more__link:hover { background: var(--paper-muted); }
.dock-more__link[aria-current='page'] { color: var(--acid-ink); background: var(--acid); border-color: transparent; }
.dock-more__signout { display: flex; align-items: center; gap: 8px; min-height: 44px; margin-top: 12px; color: var(--danger); font-size: 14px; }
@media (max-width: 1023px) {
  .dock { bottom: max(8px, env(safe-area-inset-bottom)); width: min(480px, calc(100vw - 16px)); max-width: calc(100vw - 16px); display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 0; padding: 6px; }
  .dock-item { width: 100%; min-width: 0; height: 52px; }
  .dock-label { position: static; width: auto; max-width: 100%; padding: 0; overflow: hidden; border: 0; color: inherit; background: transparent; box-shadow: none; font-size: 11px; opacity: 1; visibility: visible; transform: none; text-overflow: ellipsis; }
  .dock-item:hover, .dock-item:hover .dock-label, .dock-item:focus-visible .dock-label { transform: none; }
  .dock-item--secondary, .dock-auth-sep { display: none; }
  .dock-item--more { display: flex; }
}
@media (prefers-reduced-motion: reduce) { .dock-item, .dock-label { transition: none; } .dock-item:hover { transform: none; } }

/* Captions are navigation content, not hover-only tooltips. Full names stay in title. */
@media (min-width: 1024px) {
 .dock { width: var(--home-dock-width, clamp(760px, 58vw, 900px)); gap: 4px; padding: 10px; }
 .dock-item { flex: 1 1 0; width: auto; min-width: 0; height: 52px; gap: 3px; padding: 3px 2px; }
 .dock-label, .dock-item:hover .dock-label, .dock-item:focus-visible .dock-label {
   position: static; width: auto; max-width: 100%; padding: 0; border: 0; border-radius: 0;
   background: none; box-shadow: none; color: inherit; font-size: 10px; line-height: 14px;
   opacity: 1; visibility: visible; transform: none; overflow: hidden; text-overflow: ellipsis;
 }
 .dock-item--wide { flex-grow: 1.3; }
 .dock-icon, .dock-icon :deep(svg) { width: 24px; height: 24px; flex-shrink: 0; }
}
@media (min-width: 1024px) and (max-width: 1199px) {
 .dock-item { height: 48px; }
}
@media (min-width: 1024px) and (max-height: 700px) {
 .dock { padding: 6px; }
}

</style>
