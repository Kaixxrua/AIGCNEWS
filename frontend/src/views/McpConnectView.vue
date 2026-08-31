<script setup lang="ts">
import { onBeforeUnmount, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import SpinnerLoader from '@/components/SpinnerLoader.vue'
import { useClipboard } from '@/composables/useClipboard'
import { useMcpConnectController } from '@/composables/useMcpConnectController'
import McpSetupWizard from '@/components/mcp/McpSetupWizard.vue'
import { formatLocaleDate } from '@/i18n/formatters'
import { useAuthStore } from '@/stores/authStore'
import { useLoginPrompt } from '@/composables/useLoginPrompt'

const { t } = useI18n()
const authStore = useAuthStore()
const router = useRouter()
const { copy } = useClipboard()
const { requestLogin } = useLoginPrompt()

const controller = useMcpConnectController({
  copy,
  isLoggedIn: () => authStore.isLoggedIn,
  navigateToLogin: async () => { requestLogin('/mcp') },
  translate: t,
})

const {
  clearAuthenticatedState,
  copiedKey,
  copyHostInstruction,
  deletingId,
  displayedPublicTools,
  dispose,
  loadTokens,
  loadingTokens,
  normalizedEndpoint,
  removeToken,
  tokens,
  tokenStatus,
} = controller

const heroPillKeys = ['noAuth', 'publicTools', 'streamableHttp'] as const
const tokenStatusLabel = (status: ReturnType<typeof tokenStatus>) => t(`mcp.${status}`)
const formatDate = (value?: string | null) => value
  ? formatLocaleDate(value, { dateStyle: 'medium', timeStyle: 'short' })
  : t('common.never')

// /mcp 是网站配置页，路由守卫负责导航时门禁；auth 在挂载后异步恢复时，
// 这里补上与 DSH 相同的 fail-closed 页面门禁，避免游客短暂看到配置或触发 Token API。
watch(
  () => authStore.status,
  (status) => {
    if (status === 'authenticated') {
      void loadTokens()
      return
    }
    clearAuthenticatedState()
    if (status === 'anonymous') {
      void router.replace({ path: '/login', query: { redirect: '/mcp' } })
    }
  },
  { immediate: true },
)

onBeforeUnmount(dispose)
</script>

<template>
  <div class="mcp-connect-page flex h-full min-h-0 flex-col overflow-hidden">
    <div class="min-h-0 flex-1 overflow-y-auto px-4 py-5 md:px-8 md:py-8">
      <div class="mx-auto flex max-w-7xl flex-col gap-5 pb-24">
        <template v-if="authStore.status === 'authenticated'">
          <section class="glass-card relative overflow-hidden p-4 md:p-5">
            <div class="mcp-grid-overlay" />
            <div class="relative z-10">
              <div class="mb-3 flex flex-wrap gap-2">
                <span v-for="pillKey in heroPillKeys" :key="pillKey" class="rounded-full border border-cyan-200/60 bg-cyan-50/75 px-2.5 py-1 text-2xs font-semibold uppercase tracking-[0.12em] text-cyan-700">{{ t(`mcp.${pillKey}`) }}</span>
              </div>
              <p class="text-2xs font-semibold uppercase tracking-[0.28em] text-stone-400">{{ t('mcp.serverEyebrow') }}</p>
              <h1 class="mt-2 max-w-3xl font-serif text-2xl font-semibold leading-tight text-stone-900 md:text-3xl">{{ t('mcp.title') }}</h1>
              <p class="mt-2 max-w-3xl text-sm leading-6 text-stone-500">{{ t('mcp.description') }}</p>
              <div class="mt-3 inline-flex max-w-full flex-wrap items-center gap-2 rounded-[20px] border border-card/90 bg-card/75 px-3 py-2 shadow-sm">
                <span class="text-2xs font-semibold uppercase tracking-[0.18em] text-stone-400">{{ t('mcp.publicEndpoint') }}</span>
                <span class="break-all font-mono text-xs text-stone-700">{{ normalizedEndpoint }}</span>
              </div>
              <div v-if="!authStore.isMember" class="mt-3 flex flex-wrap items-center gap-x-3 gap-y-2 rounded-[20px] border border-amber-200 bg-amber-50/70 px-3 py-2">
                <p class="min-w-0 flex-1 basis-64 text-xs leading-5 text-amber-900">{{ t('mcp.quota.free') }}</p>
                <RouterLink to="/membership" class="btn-secondary shrink-0 text-xs">{{ t('mcp.quota.vipCta') }}</RouterLink>
              </div>
            </div>
          </section>

          <McpSetupWizard :controller="controller" />

          <section class="glass-card flex flex-wrap items-center justify-between gap-4 p-4 md:p-5" :aria-label="t('mcp.dshPlugin.kicker')">
            <div class="min-w-0 flex-1 basis-72">
              <p class="text-2xs font-semibold uppercase tracking-[0.22em] text-stone-400">{{ t('mcp.dshPlugin.kicker') }}</p>
              <h2 class="mt-1 text-base font-semibold text-stone-800">{{ t('mcp.dshPlugin.crossLinkTitle') }}</h2>
              <p class="mt-1 max-w-3xl text-xs leading-5 text-stone-500">{{ t('mcp.dshPlugin.crossLinkDescription') }}</p>
            </div>
            <RouterLink to="/dsh" class="btn-primary justify-center text-xs">{{ t('mcp.dshPlugin.openPage') }} →</RouterLink>
          </section>

          <section class="glass-card p-5 md:p-6">
            <div class="flex items-center justify-between gap-3"><div><p class="text-xs font-semibold uppercase tracking-[0.2em] text-stone-400">{{ t('mcp.tokenManagement') }}</p><h2 class="mt-1 text-lg font-semibold text-stone-800">{{ t('mcp.tokenTitle') }}</h2></div><button class="btn-secondary text-xs" :disabled="loadingTokens" @click="loadTokens">{{ t(loadingTokens ? 'common.refreshing' : 'common.refresh') }}</button></div>
            <SpinnerLoader v-if="loadingTokens && !tokens.length" class="mt-4 min-h-[180px]" />
            <div v-else-if="tokens.length" class="mcp-token-list mt-4 grid content-start gap-3 pr-1"><div v-for="item in tokens" :key="item.id" class="grid gap-3 rounded-[20px] border border-stone-200 bg-card/70 p-4 md:h-24 md:grid-cols-[minmax(0,1fr)_auto] md:items-center md:overflow-hidden"><div class="min-w-0"><div class="flex flex-wrap items-center gap-2"><span class="min-w-0 max-w-full truncate font-semibold text-stone-800" :title="item.client_label || item.client_type">{{ item.client_label || item.client_type }}</span><span class="shrink-0 rounded-full px-2 py-0.5 text-2xs" :class="tokenStatus(item) === 'valid' ? 'bg-[var(--token-valid-bg)] text-[var(--projects-success)]' : 'bg-stone-100 text-stone-500'">{{ tokenStatusLabel(tokenStatus(item)) }}</span></div><p class="mt-2 truncate font-mono text-xs text-stone-500" :title="item.token_hint">{{ item.token_hint }}</p><p class="mt-1 truncate text-2xs text-stone-400">{{ t('mcp.tokenCreatedUsed', { created: formatDate(item.created_at), used: formatDate(item.last_used_at) }) }}</p></div><button class="btn-secondary shrink-0 text-xs text-rose-700" :disabled="deletingId === item.id" @click="removeToken(item)">{{ t(deletingId === item.id ? 'mcp.deleting' : 'common.delete') }}</button></div></div>
            <p v-else-if="!loadingTokens" class="mt-4 rounded-2xl bg-stone-50 p-5 text-sm text-stone-500">{{ t('mcp.noTokens') }}</p>
          </section>

          <details class="mcp-resources glass-card p-5 md:p-6">
        <summary class="mcp-resources-summary">
          <span class="text-sm font-semibold text-stone-700">{{ t('mcp.wizard.resourcesToggle') }}</span>
          <span class="mcp-resources-hint text-2xs font-semibold text-stone-400" aria-hidden="true"></span>
        </summary>
        <div class="mt-5 flex flex-col gap-6">
          <section>
            <div class="flex flex-wrap items-start justify-between gap-4">
              <div><p class="text-xs font-semibold uppercase tracking-[0.2em] text-stone-400">{{ t('mcp.publicTools') }}</p><h2 class="mt-1 text-lg font-semibold text-stone-800">{{ t('mcp.publicToolsTitle') }}</h2><p class="mt-2 max-w-3xl text-sm leading-6 text-stone-500">{{ t('mcp.publicToolsDescription') }}</p></div>
              <span class="rounded-full bg-stone-100 px-3 py-1 text-2xs text-stone-500">{{ t('mcp.toolCount', { count: displayedPublicTools.length }) }}</span>
            </div>
            <div class="mt-4 grid gap-2 md:grid-cols-2 xl:grid-cols-3"><div v-for="tool in displayedPublicTools" :key="tool.name" class="rounded-2xl border border-stone-200 bg-card/70 px-3 py-2"><p class="font-mono text-2xs font-semibold text-stone-700">{{ tool.name }}</p><p class="mt-1 text-2xs leading-4 text-stone-400">{{ t(tool.descriptionKey) }}</p></div></div>
          </section>


          <section class="border-t border-stone-200 pt-5">
            <div class="flex flex-wrap items-start justify-between gap-4">
              <div><p class="text-xs font-semibold uppercase tracking-[0.2em] text-stone-400">{{ t('mcp.routing') }}</p><h2 class="mt-1 text-lg font-semibold text-stone-800">{{ t('mcp.routingTitle') }}</h2><p class="mt-2 max-w-3xl text-sm leading-6 text-stone-500">{{ t('mcp.routingDescription') }}</p></div>
              <button class="btn-secondary text-xs" @click="copyHostInstruction">{{ t(copiedKey === 'host-instruction' ? 'mcp.copied' : 'mcp.copyHost') }}</button>
            </div>
            <div class="mt-4 grid gap-3 md:grid-cols-3">
              <div class="rounded-2xl border border-cyan-100 bg-cyan-50/60 p-4"><p class="font-mono text-2xs font-semibold text-cyan-800">{{ t('mcp.aiArtifacts') }}</p><p class="mt-2 text-xs leading-5 text-cyan-900">search_github_ai_projects</p></div>
              <div class="rounded-2xl border border-stone-200 bg-card/70 p-4"><p class="font-mono text-2xs font-semibold text-stone-600">{{ t('mcp.nonAi') }}</p><p class="mt-2 text-xs leading-5 text-stone-800">search_github_projects</p></div>
              <div class="rounded-2xl border border-violet-100 bg-violet-50/60 p-4"><p class="font-mono text-2xs font-semibold text-violet-700">{{ t('mcp.papers') }}</p><p class="mt-2 text-xs leading-5 text-violet-900">search_papers</p></div>
            </div>
            <div class="mt-4 rounded-2xl border border-amber-200 bg-amber-50/70 p-4"><p class="text-xs font-semibold text-amber-900">{{ t('mcp.hostPriorityTitle') }}</p><p class="mt-1 text-xs leading-5 text-amber-800">{{ t('mcp.hostPriorityDescription') }}</p></div>
          </section>
        </div>
          </details>
        </template>

        <section v-if="authStore.status === 'initializing' || authStore.status === 'anonymous'" class="glass-card p-5 md:p-6">
          <p class="text-xs text-stone-500">{{ t('mcp.authRestoring') }}</p>
        </section>
        <section v-else-if="authStore.status === 'degraded'" class="glass-card p-5 md:p-6">
          <p class="rounded bg-rose-50 p-3 text-xs text-rose-700">{{ t('mcp.authDegraded') }} <button type="button" class="underline" @click="authStore.initFromStorage()">{{ t('mcp.authRetry') }}</button></p>
        </section>
      </div>
    </div>
  </div>
</template>

<style scoped>
.mcp-connect-page {
  --paper: var(--projects-paper);
  --paper-light: var(--projects-paper-light);
  --ink: var(--projects-accent);
  --muted: var(--dash-muted);
  --acid: var(--projects-acid);
  --acid-soft: var(--projects-acid-soft);
  position: relative;
  color: var(--ink);
  background: var(--paper);
  font-family: Inter, ui-sans-serif, system-ui, sans-serif;
}

.mcp-connect-page::before {
  content: '';
  position: fixed;
  inset: 0;
  pointer-events: none;
  background-image: linear-gradient(rgb(var(--ink-grid-rgb) / .035) 1px, transparent 1px);
  background-size: 100% 32px;
}

.mcp-grid-overlay {
  position: absolute;
  inset: 0;
  opacity: .32;
  background-image: linear-gradient(rgb(var(--ink-grid-rgb) / .08) 1px, transparent 1px), linear-gradient(90deg, rgb(var(--ink-grid-rgb) / .08) 1px, transparent 1px);
  background-size: 34px 34px;
  pointer-events: none;
}

.mcp-token-list {
  max-height: min(28rem, 55vh);
  overflow-y: auto;
  overscroll-behavior: contain;
  scrollbar-gutter: stable;
}

.mcp-quick-command {
  max-height: 16rem;
  white-space: pre-wrap;
  word-break: break-all;
}

.mcp-resources-summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  cursor: pointer;
  list-style: none;
  border: 1px solid var(--ink);
  border-radius: 4px;
  padding: 10px 14px;
  background: var(--acid-soft);
  color: var(--ink);
}

.mcp-resources-summary::-webkit-details-marker {
  display: none;
}

.mcp-resources-hint::after {
  content: '▸';
  display: inline-block;
  font-size: 12px;
  transition: transform 160ms cubic-bezier(.22, .61, .36, 1);
}

.mcp-resources[open] .mcp-resources-hint::after {
  transform: rotate(90deg);
}

.mcp-connect-page :deep(.glass-card) {
  border: 1px solid var(--ink);
  border-radius: 6px;
  background: rgb(var(--projects-paper-light-rgb) / .94);
  box-shadow: 4px 4px 0 var(--shadow-hard);
  backdrop-filter: none;
}

.mcp-connect-page :deep(.font-serif) { font-family: Inter, ui-sans-serif, system-ui, sans-serif; }
.mcp-connect-page :deep(h1),
.mcp-connect-page :deep(h2) { color: var(--ink); font-weight: 850; letter-spacing: -.045em; }
.mcp-connect-page :deep(.text-stone-400),
.mcp-connect-page :deep(.text-stone-500) { color: var(--muted); }

.mcp-connect-page :deep(.rounded-full),
.mcp-connect-page :deep(.rounded-2xl),
.mcp-connect-page :deep(.rounded-xl),
.mcp-connect-page :deep([class*="rounded-["]) { border-radius: 4px; }

.mcp-connect-page :deep(.border-cyan-200\/60),
.mcp-connect-page :deep(.border-cyan-300),
.mcp-connect-page :deep(.border-cyan-100) { border-color: var(--ink); }
.mcp-connect-page :deep(.bg-cyan-50),
.mcp-connect-page :deep(.bg-cyan-50\/70),
.mcp-connect-page :deep(.bg-cyan-50\/75) { background: var(--acid); }
.mcp-connect-page :deep(.text-cyan-700),
.mcp-connect-page :deep(.text-cyan-800\/80),
.mcp-connect-page :deep(.text-cyan-900) { color: var(--projects-on-acid); }

.mcp-connect-page :deep(button),
.mcp-connect-page :deep(.btn-primary),
.mcp-connect-page :deep(.btn-secondary) {
  border-radius: 4px;
  font-weight: 800;
  box-shadow: none;
}
.mcp-connect-page :deep(.btn-primary) { border: 1px solid var(--ink); color: var(--mcp-btn-label); background: var(--ink); }
.mcp-connect-page :deep(.btn-primary:not(:disabled):hover) { border-color: var(--ink); color: var(--projects-on-acid); background: var(--acid); transform: none; }
.mcp-connect-page :deep(.btn-secondary) { border: 1px solid var(--ink); color: var(--ink); background: var(--paper-light); }
.mcp-connect-page :deep(.btn-secondary:not(:disabled):hover),
.mcp-connect-page :deep(.mcp-choice:hover) { border-color: var(--ink); color: var(--ink); background: var(--acid-soft); transform: none; }
.mcp-connect-page :deep(.mcp-choice--active),
.mcp-connect-page :deep(.mcp-choice--active:hover) { border-color: var(--ink); color: var(--projects-on-acid); background: var(--acid); }
.mcp-connect-page :deep(input),
.mcp-connect-page :deep(.input) { border-color: var(--ink); border-radius: 4px; background: var(--paper-light); box-shadow: none; }
.mcp-connect-page :deep(input:focus),
.mcp-connect-page :deep(.input:focus) { border-color: var(--ink); box-shadow: 0 0 0 3px var(--acid); }

@media (prefers-reduced-motion: reduce) {
  .mcp-connect-page *, .mcp-connect-page *::before, .mcp-connect-page *::after { scroll-behavior: auto !important; transition-duration: .01ms !important; animation-duration: .01ms !important; }
}

.text-2xs { font-size: .68rem; }
</style>
