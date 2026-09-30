<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import FavoritesLink from '@/components/FavoritesLink.vue'
import PwaInstallLink from '@/components/PwaInstallLink.vue'
import GitHubLink from '@/components/GitHubLink.vue'
import { Menu, X, UserRound, LogOut } from 'lucide-vue-next'
import { isNavigationItemActive, type NavigationItem } from '@/features/navigation/navigationModel'
import { vIndicator } from '@/motion/indicator'

const props = defineProps<{
  items: readonly NavigationItem[]
  currentPath: string
  currentQuery?: Readonly<Record<string, unknown>>
  isAdmin: boolean
  isLoggedIn: boolean
  alertItems?: readonly string[]
}>()
const emit = defineEmits<{ login: []; logout: []; accountSettings: [] }>()
const { t } = useI18n()
const alertLabel = (path: string) => t(path === '/subscriptions' ? 'tracking.unread' : 'navigation.monitorAlert')
const infringementMailto = computed(() => `mailto:kaixxrua@gmail.com?subject=${encodeURIComponent(t('footer.infringement'))}`)
const dialog = ref<HTMLDialogElement>()
const menuButton = ref<HTMLButtonElement>()
const menuOpen = ref(false)
const primaryPaths = ['/', '/projects', '/report', '/mcp', '/subscriptions']
const accessibleItems = computed(() => props.items.filter(item =>
  (!item.requiresAdmin || props.isAdmin) && (!item.requiresAuth || props.isLoggedIn),
))
const primaryItems = computed(() => accessibleItems.value.filter(item => primaryPaths.includes(item.to)))
const secondaryItems = computed(() => accessibleItems.value.filter(item => !primaryPaths.includes(item.to)))
const isActive = (item: NavigationItem) => isNavigationItemActive(item, props.currentPath, props.currentQuery)
const moreActive = computed(() => secondaryItems.value.some(isActive))
const moreAlert = computed(() => secondaryItems.value.some(item => props.alertItems?.includes(item.to)))

function openMenu() {
  menuButton.value?.focus()
  dialog.value?.showModal()
  menuOpen.value = true
}
function closeMenu() {
  dialog.value?.close()
  menuOpen.value = false
}
function onClosed() {
  menuOpen.value = false
}
function accountAction(action: 'login' | 'logout' | 'accountSettings') {
  closeMenu()
  if (action === 'login') emit('login')
  else if (action === 'logout') emit('logout')
  else emit('accountSettings')
}
watch([() => props.currentPath, () => props.currentQuery, () => props.isLoggedIn], closeMenu)
onBeforeUnmount(closeMenu)
</script>

<template>
  <nav v-indicator="{ active: '.mobile-nav__item.is-active', follow: 'a.mobile-nav__item' }" class="mobile-nav" :aria-label="t('navigation.mainNavigation')">
    <RouterLink
      v-for="item in primaryItems" :key="item.to" :to="item.to"
      class="mobile-nav__item" :class="{ 'is-active': isActive(item) }"
      :aria-current="isActive(item) ? 'page' : undefined"
    >
      <span class="mobile-nav__icon" aria-hidden="true" v-html="item.icon" />
      <span v-if="props.alertItems?.includes(item.to)" class="mobile-nav__alert" role="img" :aria-label="alertLabel(item.to)" />
      <span>{{ item.to === '/' ? t('navigation.home') : item.labelText || t(item.labelKey) }}</span>
    </RouterLink>
    <button
      ref="menuButton" type="button" class="mobile-nav__item"
      :class="{ 'is-active': moreActive || menuOpen }"
      aria-haspopup="dialog" :aria-expanded="menuOpen" @click="openMenu"
    >
      <Menu class="mobile-nav__icon" aria-hidden="true" />
      <span>{{ t('navigation.more') }}</span>
      <span v-if="moreAlert" class="mobile-nav__alert" :aria-label="t('navigation.monitorAlert')" />
    </button>

    <Teleport to="body">
      <dialog ref="dialog" class="mobile-menu" aria-labelledby="mobile-menu-title" @close="onClosed" @click.self="closeMenu">
        <div class="mobile-menu__content">
          <header class="mobile-menu__header">
            <h2 id="mobile-menu-title">{{ t('navigation.more') }}</h2>
            <button type="button" :aria-label="t('common.close')" autofocus @click="closeMenu"><X aria-hidden="true" /></button>
          </header>
          <div class="mobile-menu__links">
            <RouterLink
              v-for="item in secondaryItems" :key="item.to" :to="item.to"
              class="mobile-menu__link" :class="{ 'is-active': isActive(item) }"
              :aria-current="isActive(item) ? 'page' : undefined" @click="closeMenu"
            >
              <span class="mobile-nav__icon" aria-hidden="true" v-html="item.icon" />
              <span>{{ item.labelText || t(item.labelKey) }}</span>
              <span v-if="props.alertItems?.includes(item.to)" class="mobile-menu__alert" role="img" :aria-label="alertLabel(item.to)" />
            </RouterLink>
          </div>
          <div class="mobile-menu__account">
            <button v-if="!isLoggedIn" type="button" @click="accountAction('login')"><UserRound aria-hidden="true" />{{ t('navigation.loginAccount') }}</button>
            <template v-else>
              <button type="button" @click="accountAction('accountSettings')"><UserRound aria-hidden="true" />{{ t('navigation.accountSettings') }}</button>
              <button type="button" @click="accountAction('logout')"><LogOut aria-hidden="true" />{{ t('navigation.logout') }}</button>
            </template>
          </div>
          <div class="mobile-menu__utilities"><FavoritesLink /><PwaInstallLink @click="closeMenu" /><GitHubLink @click="closeMenu" /></div>
          <footer class="mobile-menu__footer">
            <RouterLink to="/disclaimer" @click="closeMenu">{{ t('footer.disclaimer') }}</RouterLink>
            <RouterLink to="/privacy" @click="closeMenu">{{ t('footer.privacy') }}</RouterLink>
            <a href="mailto:kaixxrua@gmail.com">{{ t('navigation.contact') }}</a>
            <a :href="infringementMailto">{{ t('footer.infringement') }}</a>
            <a href="https://beian.miit.gov.cn/" target="_blank" rel="noopener noreferrer nofollow">蜀ICP备2026011291号</a>
          </footer>
        </div>
      </dialog>
    </Teleport>
  </nav>
</template>

<style scoped>
.mobile-nav { position: fixed; z-index: 100; inset: auto max(8px, env(safe-area-inset-right)) max(8px, env(safe-area-inset-bottom)) max(8px, env(safe-area-inset-left)); display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 2px; padding: 6px; background: var(--dock-surface); border: 1px solid var(--dock-edge); border-radius: 16px; box-shadow: 0 8px 24px rgb(17 25 10 / .22); }
.mobile-nav__item { position: relative; display: flex; min-width: 0; min-height: 50px; flex-direction: column; align-items: center; justify-content: center; gap: 4px; border-radius: 10px; color: var(--dock-text); font-size: 11px; font-weight: 600; line-height: 1.3; text-decoration: none; }
.mobile-nav__item.is-active { color: var(--acid-ink); background: var(--acid); }
/* 选中底色由 v-indicator 画在导航条的 ::before 上滑动；打开「更多」时滑到菜单键，关上再滑回来。 */
.mobile-nav::before { z-index: -1; border-radius: 10px; background: var(--acid); }
.mobile-nav__item { transition: color 160ms ease; }
.mobile-nav[data-indicator] .mobile-nav__item.is-active { background: transparent; transition-delay: 70ms; }
.mobile-nav[data-indicator-pending] .mobile-nav__item.is-active { color: var(--dock-text); transition-delay: 0ms; }
.mobile-nav .mobile-nav__item[data-indicator-target] { color: var(--acid-ink); transition-delay: 70ms; }
.mobile-nav__item:focus-visible { outline: 2px solid var(--ink); outline-offset: 2px; }
.mobile-nav__icon { display: inline-flex; flex: 0 0 20px; width: 20px; height: 20px; }
.mobile-nav__icon :deep(svg) { width: 20px; height: 20px; }
.mobile-nav__alert, .mobile-menu__alert { width: 8px; height: 8px; border-radius: 50%; background: var(--error-accent); }
.mobile-nav__alert { position: absolute; top: 6px; right: 20%; }
.mobile-menu { position: fixed; inset: auto 0 0; width: 100%; max-width: 40rem; max-height: calc(100dvh - 24px); margin: 0 auto; padding: 0; overflow-y: auto; overscroll-behavior: contain; color: var(--ink); background: var(--paper-raised); border: 1px solid var(--rule-strong); border-radius: 16px 16px 0 0; }
.mobile-menu::backdrop { background: var(--overlay-backdrop, rgb(0 0 0 / 0.45)); }
.mobile-menu__content { padding: 16px 16px max(16px, env(safe-area-inset-bottom)); }
.mobile-menu__header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
.mobile-menu__header h2 { font-size: 20px; font-weight: 700; }
.mobile-menu__header button { display: grid; width: 44px; height: 44px; place-items: center; }
.mobile-menu__links { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
.mobile-menu__link { display: flex; min-width: 0; min-height: 52px; align-items: center; gap: 10px; padding: 12px; border: 1px solid var(--rule); border-radius: 6px; font-size: 14px; overflow-wrap: anywhere; }
.mobile-menu__link.is-active { background: var(--acid-soft); border-color: var(--ink); }
.mobile-menu__account { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 16px; padding-top: 16px; border-top: 1px solid var(--rule); }
.mobile-menu__account button { display: flex; min-height: 44px; align-items: center; gap: 8px; padding: 8px 12px; border: 1px solid var(--rule); border-radius: 6px; font-size: 14px; }
.mobile-menu__account svg { width: 18px; height: 18px; }
.mobile-menu__footer { display: flex; flex-wrap: wrap; gap: 0 16px; margin-top: 16px; color: var(--ink-muted); font-size: 12px; }
.mobile-menu__footer a { display: inline-flex; min-height: 44px; align-items: center; }
.mobile-menu__utilities { display: flex; gap: 12px; margin-top: 16px; }
.mobile-menu__utilities :deep(button), .mobile-menu__utilities :deep(a) { min-width: 44px; min-height: 44px; }
</style>
