<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { useClipboard } from '../composables/useClipboard'
import { useMcpConnectController } from '../composables/useMcpConnectController'
import { mcpClientOptions } from '../features/mcp/mcpClientCatalog'
import { resolveMcpFeedback } from '../features/mcp/mcpFeedback'
import { formatLocaleDate } from '../i18n/formatters'
import { useAuthStore } from '../stores/authStore'

const { t } = useI18n()
const router = useRouter()
const authStore = useAuthStore()
const { copy } = useClipboard()
const SCOPE = 'projects:favorites:read'

const {
  clientLabel,
  clientOption,
  copiedKey,
  copyGeneratedCommand,
  copyHostInstruction,
  creating,
  deletingId,
  displayedPublicTools,
  dispose,
  endpointUrl,
  endpointWarningKey,
  loadTokens,
  loadingTokens,
  normalizedEndpoint,
  removeToken,
  selectedClient,
  selectedShell,
  setupError,
  setupNotice,
  startSetup,
  testing,
  testMessage,
  testPhases,
  testPublicHandshake,
  tokenStatus,
  tokens,
  transientCommand,
} = useMcpConnectController({
  copy,
  isLoggedIn: () => authStore.isLoggedIn,
  navigateToLogin: async () => { await router.push('/login') },
  translate: t,
})

const shellOptions = [
  { id: 'powershell' as const, label: 'PowerShell' },
  { id: 'cmd' as const, label: 'Command Prompt' },
  { id: 'bash' as const, label: 'Bash / zsh' },
]
const clientOptions = mcpClientOptions
const setupErrorDisplay = computed(() => resolveMcpFeedback(setupError.value, t))
const setupNoticeDisplay = computed(() => resolveMcpFeedback(setupNotice.value, t))
const testMessageDisplay = computed(() => resolveMcpFeedback(testMessage.value, t))
const endpointWarning = computed(() => endpointWarningKey.value ? t(endpointWarningKey.value) : '')
const setupScopeKeys = {
  user: 'user',
  'conditional-user': 'conditionalUser',
  'user-with-session-secret': 'sessionSecret',
  'import-file': 'importFile',
} as const
const setupScopeLabel = computed(() => t(`mcp.scope.${setupScopeKeys[clientOption.value.setupScope]}`))
const setupTargetDescription = computed(() => {
  if (clientOption.value.id === 'claude-code') return t('mcp.resultClaudeCode')
  if (clientOption.value.id === 'continue') return t('mcp.resultContinue', { path: clientOption.value.configPath })
  if (clientOption.value.id === 'vscode') return t('mcp.resultVsCode')
  if (clientOption.value.id === 'codex') return selectedShell.value === 'bash'
    ? t('mcp.codexResult')
    : t('mcp.resultCodexWindows')
  return t('mcp.resultImport', { path: clientOption.value.configPath })
})
const setupResultDescription = computed(() => {
  if (clientOption.value.id === 'claude-code') return t('mcp.hintClaudeCode')
  if (clientOption.value.id === 'continue') return t('mcp.hintContinue')
  if (clientOption.value.id === 'vscode') return t('mcp.hintVsCode')
  if (clientOption.value.id === 'codex') return t('mcp.hintCodex')
  return t('mcp.hintImport', { path: clientOption.value.configPath })
})
const tokenStatusLabel = (status: ReturnType<typeof tokenStatus>) => t(`mcp.${status}`)
const formatDate = (value?: string | null) => value
  ? formatLocaleDate(value, { dateStyle: 'medium', timeStyle: 'short' })
  : t('common.never')

onMounted(loadTokens)
onBeforeUnmount(dispose)
</script>

<template>
  <div class="mcp-connect-page flex h-full min-h-0 flex-col overflow-hidden">
    <div class="min-h-0 flex-1 overflow-y-auto px-4 py-5 md:px-8 md:py-8">
      <div class="mx-auto flex max-w-7xl flex-col gap-5 pb-24">
      <section class="glass-card relative overflow-hidden p-4 md:p-5">
        <div class="mcp-grid-overlay" />
        <div class="relative z-10 grid gap-4 xl:grid-cols-[1.05fr_0.95fr] xl:items-center">
          <div>
            <div class="mb-3 flex flex-wrap gap-2">
              <span v-for="pill in ['Streamable HTTP', 'Public tools', 'Private favorites']" :key="pill" class="rounded-full border border-cyan-200/60 bg-cyan-50/75 px-2.5 py-1 text-2xs font-semibold uppercase tracking-[0.12em] text-cyan-700">{{ pill }}</span>
            </div>
            <p class="text-2xs font-semibold uppercase tracking-[0.28em] text-stone-400">AIGC_NEWS MCP Server</p>
            <h1 class="mt-2 max-w-3xl font-serif text-2xl font-semibold leading-tight text-stone-900 md:text-3xl">{{ t('mcp.title') }}</h1>
            <p class="mt-2 max-w-3xl text-sm leading-6 text-stone-500">{{ t('mcp.description') }}</p>
          </div>
          <div class="rounded-[20px] border border-white/90 bg-white/75 p-4 shadow-sm">
            <p class="text-xs font-semibold uppercase tracking-[0.2em] text-stone-400">Public endpoint</p>
            <div class="mt-2 rounded-2xl border border-stone-200 bg-stone-50/80 px-3 py-2 font-mono text-xs text-stone-700">{{ normalizedEndpoint }}</div>
            <div class="mt-2 flex flex-col gap-2 sm:flex-row"><input v-model.trim="endpointUrl" class="input min-w-0 flex-1 font-mono text-xs" :aria-label="t('mcp.endpointAria')" /><button class="btn-secondary justify-center text-xs" :disabled="testing || Boolean(endpointWarning)" @click="testPublicHandshake">{{ t(testing ? 'mcp.testing' : 'mcp.publicHandshake') }}</button></div>
            <p v-if="endpointWarning" class="mt-2 text-xs text-rose-700">{{ endpointWarning }}</p>
            <p v-if="testMessageDisplay" class="mt-3 text-xs text-stone-500">{{ testMessageDisplay }}</p>
            <div class="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-3"><div v-for="phase in testPhases" :key="phase.label" class="rounded-xl border border-stone-200 bg-white p-2"><p class="text-2xs text-stone-700">{{ t(`mcp.phase.${phase.descriptionKey}`) }}</p><p class="mt-1 text-2xs" :class="phase.status === 'success' ? 'text-emerald-600' : phase.status === 'error' ? 'text-rose-600' : 'text-stone-400'">{{ phase.detail ? resolveMcpFeedback(phase.detail, t) : t(`mcp.phaseStatus.${phase.status}`) }}</p></div></div>
          </div>
        </div>
      </section>

      <section class="glass-card p-5 md:p-6">
        <div class="flex flex-wrap items-start justify-between gap-4">
          <div><p class="text-xs font-semibold uppercase tracking-[0.22em] text-stone-400">Authenticated setup</p><h2 class="mt-1 text-xl font-semibold text-stone-800">{{ t('mcp.setupTitle') }}</h2><p class="mt-2 text-sm text-stone-500">{{ t('mcp.setupDescription') }}</p></div>
          <button v-if="!authStore.isLoggedIn" class="btn-primary" @click="router.push('/login')">{{ t('mcp.loginToConfigure') }}</button>
          <span v-else class="rounded-full bg-emerald-50 px-3 py-1 text-xs font-semibold text-emerald-700">{{ t('mcp.loggedIn') }}</span>
        </div>

        <div v-if="authStore.isLoggedIn" class="mt-6 grid gap-5 xl:grid-cols-[0.9fr_1.1fr]">
          <div class="rounded-[24px] border border-stone-200/80 bg-white/65 p-5">
            <p class="text-xs font-semibold uppercase tracking-[0.18em] text-stone-400">{{ t('mcp.stepChoose') }}</p>
            <div class="mt-4 grid gap-2 sm:grid-cols-2"><button v-for="client in clientOptions" :key="client.id" class="mcp-choice rounded-[18px] border p-3 text-left" :class="selectedClient === client.id ? 'mcp-choice--active' : 'border-stone-200 bg-white'" @click="selectedClient = client.id"><span class="flex flex-wrap items-center gap-2"><span class="text-sm font-semibold text-stone-800">{{ client.label }}</span><span class="rounded-full bg-stone-100 px-2 py-0.5 text-2xs font-semibold text-stone-500">{{ t(`mcp.scope.${setupScopeKeys[client.setupScope]}`) }}</span></span><span class="mt-1 block text-2xs leading-4 text-stone-400">{{ client.description }}</span></button></div>
            <p class="mt-5 text-sm font-semibold text-stone-700">{{ t('mcp.terminal') }}</p>
            <div class="mt-2 flex flex-wrap gap-2"><button v-for="shell in shellOptions" :key="shell.id" class="mcp-choice rounded-full border px-3 py-2 text-xs" :class="selectedShell === shell.id ? 'mcp-choice--active' : 'border-stone-200 bg-white text-stone-600'" @click="selectedShell = shell.id">{{ shell.label }}</button></div>
            <label class="mt-5 block text-xs font-semibold text-stone-600">{{ t('mcp.deviceLabel') }}</label><input v-model="clientLabel" maxlength="128" class="input mt-2" :placeholder="t('mcp.devicePlaceholder')" />
          </div>

          <div class="rounded-[24px] border border-stone-200/80 bg-stone-50/70 p-5">
            <p class="text-xs font-semibold uppercase tracking-[0.18em] text-stone-400">{{ t('mcp.stepConfirm') }}</p>
            <div class="mt-4 rounded-2xl border border-cyan-100 bg-cyan-50/70 p-4"><p class="text-sm font-semibold text-cyan-900">{{ t('mcp.permission') }}</p><p class="mt-1 font-mono text-2xs text-cyan-700">{{ SCOPE }}</p><p class="mt-2 text-xs leading-5 text-cyan-800/80">{{ t('mcp.bearerMemory') }}</p></div>
            <div class="mt-4 rounded-2xl border border-stone-200 bg-white/75 p-4"><div class="flex flex-wrap items-center gap-2"><span class="rounded-full bg-stone-100 px-2.5 py-1 text-2xs font-semibold text-stone-600">{{ setupScopeLabel }}</span><span class="text-xs font-semibold text-stone-700">{{ clientOption.configPath }}</span></div><p class="mt-2 text-xs leading-5 text-stone-500">{{ setupTargetDescription }}</p></div>
            <p class="mt-3 text-xs leading-5 text-stone-500">{{ t('mcp.multipleTokens') }}</p>
            <button class="btn-primary mt-3 w-full justify-center" :disabled="creating" @click="startSetup">{{ t(creating ? 'mcp.creating' : clientOption.setupScope === 'import-file' ? 'mcp.generateImport' : 'mcp.generateCommand') }}</button>
            <div v-if="transientCommand" class="mt-4 rounded-2xl border border-amber-300 bg-amber-50 p-4"><p class="text-sm font-semibold text-amber-900">{{ t('mcp.bearerWarning') }}</p><p class="mt-1 text-xs font-semibold leading-5 text-amber-800">{{ t('mcp.bearerWarningDetail') }}</p><p class="mt-2 text-xs leading-5 text-amber-700">{{ t('mcp.hiddenConfig', { result: setupResultDescription }) }}</p><button class="btn-primary mt-3 text-xs" @click="copyGeneratedCommand">{{ t(copiedKey === 'command' ? 'mcp.copiedClipboard' : 'mcp.copyOneTime') }}</button></div>
            <p v-if="setupNoticeDisplay" class="mt-3 rounded-2xl bg-emerald-50 px-4 py-3 text-xs text-emerald-700">{{ setupNoticeDisplay }}</p>
            <p v-if="setupErrorDisplay" class="mt-3 rounded-2xl bg-rose-50 px-4 py-3 text-xs text-rose-700">{{ setupErrorDisplay }}</p>
          </div>
        </div>
        <div v-else class="mt-6 rounded-[24px] border border-dashed border-stone-300 bg-white/60 p-7 text-center"><p class="text-base font-semibold text-stone-700">{{ t('mcp.loginRequiredTitle') }}</p><p class="mt-2 text-sm text-stone-500">{{ t('mcp.loginRequiredDescription') }}</p></div>
      </section>

      <section v-if="authStore.isLoggedIn" class="glass-card p-5 md:p-6">
        <div class="flex items-center justify-between gap-3"><div><p class="text-xs font-semibold uppercase tracking-[0.2em] text-stone-400">Token management</p><h2 class="mt-1 text-lg font-semibold text-stone-800">{{ t('mcp.tokenTitle') }}</h2></div><button class="btn-secondary text-xs" :disabled="loadingTokens" @click="loadTokens">{{ t(loadingTokens ? 'common.refreshing' : 'common.refresh') }}</button></div>
        <div v-if="tokens.length" class="mcp-token-list mt-4 grid gap-3 pr-1"><div v-for="item in tokens" :key="item.id" class="grid gap-3 rounded-[20px] border border-stone-200 bg-white/70 p-4 md:grid-cols-[1fr_auto] md:items-center"><div><div class="flex flex-wrap items-center gap-2"><span class="font-semibold text-stone-800">{{ item.client_label || item.client_type }}</span><span class="rounded-full px-2 py-0.5 text-2xs" :class="tokenStatus(item) === 'valid' ? 'bg-emerald-50 text-emerald-700' : 'bg-stone-100 text-stone-500'">{{ tokenStatusLabel(tokenStatus(item)) }}</span></div><p class="mt-2 font-mono text-xs text-stone-500">{{ item.token_hint }}</p><p class="mt-1 text-2xs text-stone-400">{{ t('mcp.tokenCreatedUsed', { created: formatDate(item.created_at), used: formatDate(item.last_used_at) }) }}</p></div><button class="btn-secondary text-xs text-rose-700" :disabled="deletingId === item.id" @click="removeToken(item)">{{ t(deletingId === item.id ? 'mcp.deleting' : 'common.delete') }}</button></div></div>
        <p v-else-if="!loadingTokens" class="mt-4 rounded-2xl bg-stone-50 p-5 text-sm text-stone-500">{{ t('mcp.noTokens') }}</p>
      </section>

      <section class="glass-card p-5 md:p-6">
        <div class="flex flex-wrap items-start justify-between gap-4">
          <div><p class="text-xs font-semibold uppercase tracking-[0.2em] text-stone-400">MCP-first routing</p><h2 class="mt-1 text-lg font-semibold text-stone-800">{{ t('mcp.routingTitle') }}</h2><p class="mt-2 max-w-3xl text-sm leading-6 text-stone-500">{{ t('mcp.routingDescription') }}</p></div>
          <button class="btn-secondary text-xs" @click="copyHostInstruction">{{ t(copiedKey === 'host-instruction' ? 'mcp.copied' : 'mcp.copyHost') }}</button>
        </div>
        <div class="mt-4 grid gap-3 md:grid-cols-3">
          <div class="rounded-2xl border border-cyan-100 bg-cyan-50/60 p-4"><p class="font-mono text-2xs font-semibold text-cyan-800">AI / Agent / MCP / RAG</p><p class="mt-2 text-xs leading-5 text-cyan-900">search_github_ai_projects</p></div>
          <div class="rounded-2xl border border-stone-200 bg-white/70 p-4"><p class="font-mono text-2xs font-semibold text-stone-600">{{ t('mcp.nonAi') }}</p><p class="mt-2 text-xs leading-5 text-stone-800">search_github_projects</p></div>
          <div class="rounded-2xl border border-violet-100 bg-violet-50/60 p-4"><p class="font-mono text-2xs font-semibold text-violet-700">{{ t('mcp.papers') }}</p><p class="mt-2 text-xs leading-5 text-violet-900">search_papers</p></div>
        </div>
        <div class="mt-4 rounded-2xl border border-amber-200 bg-amber-50/70 p-4"><p class="text-xs font-semibold text-amber-900">{{ t('mcp.hostPriorityTitle') }}</p><p class="mt-1 text-xs leading-5 text-amber-800">{{ t('mcp.hostPriorityDescription') }}</p></div>
      </section>

      <section class="glass-card p-5">
        <div class="flex flex-wrap items-center justify-between gap-2"><div><p class="text-sm font-semibold text-stone-800">{{ t('mcp.publicTools') }}</p><p class="mt-1 text-xs text-stone-500">{{ t('mcp.publicToolsDescription') }}</p></div><span class="rounded-full bg-stone-100 px-3 py-1 text-2xs text-stone-500">{{ t('mcp.toolCount', { count: displayedPublicTools.length }) }}</span></div>
        <div class="mt-3 grid gap-2 md:grid-cols-2 xl:grid-cols-3"><div v-for="tool in displayedPublicTools" :key="tool.name" class="rounded-2xl border border-stone-200 bg-white/70 px-3 py-2"><p class="font-mono text-2xs font-semibold text-stone-700">{{ tool.name }}</p><p class="mt-1 text-2xs leading-4 text-stone-400">{{ tool.description }}</p></div></div>
      </section>
      </div>
    </div>
  </div>
</template>

<style scoped>
.mcp-connect-page {
  --paper: #f3f0e6;
  --paper-light: #fffdf5;
  --ink: #11110f;
  --muted: #68655d;
  --acid: #c7f432;
  --acid-soft: #f1f8d2;
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
  background-image: linear-gradient(rgba(17, 17, 15, .035) 1px, transparent 1px);
  background-size: 100% 32px;
}

.mcp-grid-overlay {
  position: absolute;
  inset: 0;
  opacity: .32;
  background-image: linear-gradient(rgba(17,17,15,.08) 1px, transparent 1px), linear-gradient(90deg, rgba(17,17,15,.08) 1px, transparent 1px);
  background-size: 34px 34px;
  pointer-events: none;
}

.mcp-token-list {
  max-height: min(28rem, 55vh);
  overflow-y: auto;
  overscroll-behavior: contain;
  scrollbar-gutter: stable;
}

.mcp-connect-page :deep(.glass-card) {
  border: 1px solid var(--ink);
  border-radius: 6px;
  background: rgba(255, 253, 245, .94);
  box-shadow: 4px 4px 0 var(--ink);
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
.mcp-connect-page :deep(.text-cyan-900) { color: var(--ink); }

.mcp-connect-page :deep(button),
.mcp-connect-page :deep(.btn-primary),
.mcp-connect-page :deep(.btn-secondary) {
  border-radius: 4px;
  font-weight: 800;
  box-shadow: none;
}
.mcp-connect-page :deep(.btn-primary) { border: 1px solid var(--ink); color: var(--acid); background: var(--ink); }
.mcp-connect-page :deep(.btn-primary:not(:disabled):hover) { border-color: var(--ink); color: var(--ink); background: var(--acid); transform: none; }
.mcp-connect-page :deep(.btn-secondary) { border: 1px solid var(--ink); color: var(--ink); background: var(--paper-light); }
.mcp-connect-page :deep(.btn-secondary:not(:disabled):hover),
.mcp-connect-page :deep(.mcp-choice:hover) { border-color: var(--ink); color: var(--ink); background: var(--acid-soft); transform: none; }
.mcp-connect-page :deep(.mcp-choice--active),
.mcp-connect-page :deep(.mcp-choice--active:hover) { border-color: var(--ink); color: var(--ink); background: var(--acid); }
.mcp-connect-page :deep(input),
.mcp-connect-page :deep(.input) { border-color: var(--ink); border-radius: 4px; background: var(--paper-light); box-shadow: none; }
.mcp-connect-page :deep(input:focus),
.mcp-connect-page :deep(.input:focus) { border-color: var(--ink); box-shadow: 0 0 0 3px var(--acid); }

.text-2xs { font-size: .68rem; }
</style>
