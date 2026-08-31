<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import type { McpConnectController } from '@/composables/useMcpConnectController'
import { mcpClientOptions, type McpClientOption } from '@/features/mcp/mcpClientCatalog'
import { resolveMcpFeedback } from '@/features/mcp/mcpFeedback'

const SCOPE = 'projects:favorites:read'

const props = defineProps<{
  controller: McpConnectController
}>()

const { t } = useI18n()

const {
  clientDisplayLabel,
  clientLabel,
  clientOption,
  copiedKey,
  copyGeneratedCommand,
  copyQuickCommand,
  creating,
  endpointUrl,
  endpointWarningKey,
  normalizedEndpoint,
  quickCommand,
  selectedClient,
  selectedShell,
  setupError,
  setupNotice,
  startSetup,
  testing,
  testMessage,
  testPhases,
  testPublicHandshake,
  transientCommand,
} = props.controller

const stepTitleKeys = [
  'mcp.wizard.stepClient',
  'mcp.wizard.stepCommand',
  'mcp.wizard.stepVerify',
] as const
const stepDescriptionKeys = [
  'mcp.wizard.stepClientDescription',
  'mcp.wizard.stepCommandDescription',
  'mcp.wizard.stepVerifyDescription',
] as const

const currentStep = ref(0)
const rootEl = ref<HTMLElement | null>(null)
const isFirst = computed(() => currentStep.value === 0)
const isLast = computed(() => currentStep.value === stepTitleKeys.length - 1)

const shellOptions = [
  { id: 'powershell' as const, label: 'PowerShell', labelKey: '' },
  { id: 'cmd' as const, label: '', labelKey: 'mcp.commandPrompt' },
  { id: 'bash' as const, label: 'Bash / zsh', labelKey: '' },
]
const clientOptions = mcpClientOptions
const setupScopeKeys = {
  user: 'user',
  'conditional-user': 'conditionalUser',
  'user-with-session-secret': 'sessionSecret',
  'import-file': 'importFile',
} as const
const setupScopeLabel = computed(() => t(`mcp.scope.${setupScopeKeys[clientOption.value.setupScope]}`))
const clientConfigTarget = (option: McpClientOption) => (option.configPathKey ? t(option.configPathKey) : option.configPath)
const setupTargetDescription = computed(() => {
  if (clientOption.value.id === 'claude-code') return t('mcp.resultClaudeCode')
  if (clientOption.value.id === 'continue') return t('mcp.resultContinue', { path: clientConfigTarget(clientOption.value) })
  if (clientOption.value.id === 'vscode') return t('mcp.resultVsCode')
  if (clientOption.value.id === 'codex') return selectedShell.value === 'bash'
    ? t('mcp.codexResult')
    : t('mcp.resultCodexWindows')
  return t('mcp.resultImport', { path: clientConfigTarget(clientOption.value) })
})
const setupResultDescription = computed(() => {
  if (clientOption.value.id === 'claude-code') return t('mcp.hintClaudeCode')
  if (clientOption.value.id === 'continue') return t('mcp.hintContinue')
  if (clientOption.value.id === 'vscode') return t('mcp.hintVsCode')
  if (clientOption.value.id === 'codex') return t('mcp.hintCodex')
  return t('mcp.hintImport', { path: clientConfigTarget(clientOption.value) })
})
const setupErrorDisplay = computed(() => resolveMcpFeedback(setupError.value, t))
const setupNoticeDisplay = computed(() => resolveMcpFeedback(setupNotice.value, t))
const testMessageDisplay = computed(() => resolveMcpFeedback(testMessage.value, t))
const endpointWarning = computed(() => endpointWarningKey.value ? t(endpointWarningKey.value) : '')

const scrollBehavior = (): ScrollBehavior => (
  typeof window !== 'undefined'
  && typeof window.matchMedia === 'function'
  && window.matchMedia('(prefers-reduced-motion: reduce)').matches
    ? 'auto'
    : 'smooth'
)

const scrollToWizardTop = async () => {
  await nextTick()
  rootEl.value?.scrollIntoView?.({ block: 'start', behavior: scrollBehavior() })
}

const goTo = async (index: number) => {
  if (index === currentStep.value) return
  currentStep.value = index
  await scrollToWizardTop()
}
const goPrev = () => goTo(Math.max(0, currentStep.value - 1))
const goNext = () => goTo(Math.min(stepTitleKeys.length - 1, currentStep.value + 1))
</script>

<template>
  <section ref="rootEl" class="mcp-wizard glass-card scroll-mt-4 p-5 md:p-6" :aria-label="t('mcp.wizard.ariaLabel')">
    <ol class="mcp-wizard-steps flex list-none flex-wrap items-stretch gap-y-2 p-0">
      <template v-for="(titleKey, index) in stepTitleKeys" :key="titleKey">
        <li class="mcp-wizard-step">
          <button
            type="button"
            class="mcp-step-dot"
            :class="index === currentStep ? 'mcp-step-dot--active' : ''"
            :aria-current="index === currentStep ? 'step' : undefined"
            @click="goTo(index)"
          >
            <span class="mcp-step-num" aria-hidden="true">{{ index + 1 }}</span>
            <span class="mcp-step-label">{{ t(titleKey) }}</span>
          </button>
        </li>
        <li v-if="index < stepTitleKeys.length - 1" class="mcp-step-arrow" aria-hidden="true">→</li>
      </template>
    </ol>
    <p class="mt-3 text-xs leading-5 text-stone-500">{{ t(stepDescriptionKeys[currentStep]!) }}</p>

    <Transition name="mcp-step" mode="out-in">
      <div :key="currentStep" class="mcp-step-panel mt-5">
        <div v-if="currentStep === 0">
          <p class="text-xs font-semibold uppercase tracking-[0.18em] text-stone-400">{{ t('mcp.chooseClient') }}</p>
          <div class="mt-4 grid gap-2 sm:grid-cols-2 xl:grid-cols-3"><button v-for="client in clientOptions" :key="client.id" type="button" class="mcp-choice rounded-[18px] border p-3 text-left" :class="selectedClient === client.id ? 'mcp-choice--active' : 'border-stone-200 bg-card'" @click="selectedClient = client.id"><span class="flex flex-wrap items-center gap-2"><span class="text-sm font-semibold text-stone-800">{{ clientDisplayLabel(client) }}</span><span class="rounded-full bg-stone-100 px-2 py-0.5 text-2xs font-semibold text-stone-500">{{ t(`mcp.scope.${setupScopeKeys[client.setupScope]}`) }}</span></span><span class="mt-1 block text-2xs leading-4 text-stone-400">{{ t(client.descriptionKey) }}</span></button></div>
          <p class="mt-5 text-sm font-semibold text-stone-700">{{ t('mcp.terminal') }}</p>
          <div class="mt-2 flex flex-wrap gap-2"><button v-for="shell in shellOptions" :key="shell.id" type="button" class="mcp-choice rounded-full border px-3 py-2 text-xs" :class="selectedShell === shell.id ? 'mcp-choice--active' : 'border-stone-200 bg-card text-stone-600'" @click="selectedShell = shell.id">{{ shell.labelKey ? t(shell.labelKey) : shell.label }}</button></div>
        </div>

        <div v-else-if="currentStep === 1">
          <p class="text-xs font-semibold uppercase tracking-[0.18em] text-stone-400">{{ t('mcp.quickCommandLabel') }}</p>
          <pre v-if="quickCommand" class="mcp-quick-command mt-4 overflow-auto rounded-2xl border border-stone-700 bg-stone-900 p-4 font-mono text-2xs leading-5 text-stone-100">{{ quickCommand }}</pre>
          <p v-else class="mt-4 rounded-2xl bg-rose-50 px-4 py-3 text-xs text-rose-700">{{ endpointWarning }}</p>
          <div class="mt-4 rounded-2xl border border-stone-200 bg-card/75 p-4"><div class="flex flex-wrap items-center gap-2"><span class="rounded-full bg-stone-100 px-2.5 py-1 text-2xs font-semibold text-stone-600">{{ setupScopeLabel }}</span><span class="text-xs font-semibold text-stone-700">{{ clientConfigTarget(clientOption) }}</span></div><p class="mt-2 text-xs leading-5 text-stone-500">{{ setupTargetDescription }}</p></div>
          <button type="button" class="btn-primary mt-3 w-full justify-center" :disabled="!quickCommand" @click="copyQuickCommand">{{ t(copiedKey === 'quick-command' ? 'mcp.copied' : 'mcp.copyQuick') }}</button>

          <div class="mcp-wizard-auth mt-6 border-t border-stone-200 pt-5">
            <p class="text-xs font-semibold uppercase tracking-[0.18em] text-stone-400">{{ t('mcp.favoritesAuth') }}</p>
            <div class="mt-4 rounded-2xl border border-cyan-100 bg-cyan-50/70 p-4"><p class="text-sm font-semibold text-cyan-900">{{ t('mcp.permission') }}</p><p class="mt-1 font-mono text-2xs text-cyan-700">{{ SCOPE }}</p><p class="mt-2 text-xs leading-5 text-cyan-800/80">{{ t('mcp.bearerMemory') }}</p></div>
            <label class="mt-5 block text-xs font-semibold text-stone-600">{{ t('mcp.deviceLabel') }}</label>
            <input v-model="clientLabel" maxlength="128" class="input mt-2" :placeholder="t('mcp.devicePlaceholder')" />
            <p class="mt-3 text-xs leading-5 text-stone-500">{{ t('mcp.multipleTokens') }}</p>
            <button type="button" class="btn-primary mt-4 w-full justify-center" :disabled="creating" @click="startSetup">{{ t(creating ? 'mcp.creating' : clientOption.setupScope === 'import-file' ? 'mcp.generateImport' : 'mcp.generateCommand') }}</button>
            <div v-if="transientCommand" class="mt-4 rounded-2xl border border-amber-300 bg-amber-50 p-4"><p class="text-sm font-semibold text-amber-900">{{ t('mcp.bearerWarning') }}</p><p class="mt-1 text-xs font-semibold leading-5 text-amber-800">{{ t('mcp.bearerWarningDetail') }}</p><p class="mt-2 text-xs leading-5 text-amber-700">{{ t('mcp.hiddenConfig', { result: setupResultDescription }) }}</p><button type="button" class="btn-primary mt-3 text-xs" @click="copyGeneratedCommand">{{ t(copiedKey === 'command' ? 'mcp.copiedClipboard' : 'mcp.copyOneTime') }}</button></div>
            <p v-if="setupNoticeDisplay" class="mt-3 rounded-2xl bg-[var(--token-valid-bg)] px-4 py-3 text-xs text-[var(--projects-success)]">{{ setupNoticeDisplay }}</p>
            <p v-if="setupErrorDisplay" class="mt-3 rounded-2xl bg-rose-50 px-4 py-3 text-xs text-rose-700">{{ setupErrorDisplay }}</p>
          </div>
        </div>

        <div v-else-if="currentStep === 2">
          <p class="text-xs font-semibold uppercase tracking-[0.18em] text-stone-400">{{ t('mcp.publicEndpoint') }}</p>
          <div class="mt-3 rounded-2xl border border-stone-200 bg-stone-50/80 px-3 py-2 font-mono text-xs text-stone-700">{{ normalizedEndpoint }}</div>
          <div class="mt-3 flex flex-col gap-2 sm:flex-row"><input v-model.trim="endpointUrl" class="input min-w-0 flex-1 font-mono text-xs" :aria-label="t('mcp.endpointAria')" /><button type="button" class="btn-secondary justify-center text-xs" :disabled="testing || Boolean(endpointWarning)" @click="testPublicHandshake">{{ t(testing ? 'mcp.testing' : 'mcp.publicHandshake') }}</button></div>
          <p v-if="endpointWarning" class="mt-2 text-xs text-rose-700">{{ endpointWarning }}</p>
          <p v-if="testMessageDisplay" class="mt-3 text-xs text-stone-500">{{ testMessageDisplay }}</p>
          <div class="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-3"><div v-for="phase in testPhases" :key="phase.label" class="rounded-xl border border-stone-200 bg-card p-2"><p class="text-2xs text-stone-700">{{ t(`mcp.phase.${phase.descriptionKey}`) }}</p><p class="mt-1 text-2xs" :class="phase.status === 'success' ? 'text-emerald-600' : phase.status === 'error' ? 'text-rose-600' : 'text-stone-400'">{{ phase.detail ? resolveMcpFeedback(phase.detail, t) : t(`mcp.phaseStatus.${phase.status}`) }}</p></div></div>
        </div>
      </div>
    </Transition>

      <div class="mcp-wizard-nav mt-6 flex items-center justify-between gap-3 border-t border-stone-200 pt-4">
        <button type="button" class="btn-secondary text-xs" :disabled="isFirst" @click="goPrev">← {{ t('mcp.wizard.prev') }}</button>
        <span class="text-2xs font-semibold text-stone-400">{{ t('mcp.wizard.stepProgress', { current: currentStep + 1, total: stepTitleKeys.length }) }}</span>
        <button type="button" class="btn-primary text-xs" :disabled="isLast" @click="goNext">{{ t('mcp.wizard.next') }} →</button>
      </div>
  </section>
</template>

<style scoped>
.mcp-wizard-steps {
  margin: 0;
}

.mcp-wizard-step {
  display: flex;
}

.mcp-step-dot {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  border: 1px solid var(--ink);
  border-radius: 4px;
  padding: 6px 12px;
  background: var(--paper-light);
  color: var(--ink);
  font-size: 12px;
  font-weight: 800;
  cursor: pointer;
  transition: background-color 160ms cubic-bezier(.22, .61, .36, 1), color 160ms cubic-bezier(.22, .61, .36, 1);
}

.mcp-step-num {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  border: 1px solid currentColor;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 800;
}

.mcp-step-dot--active,
.mcp-step-dot--active:hover {
  background: var(--acid);
  color: var(--projects-on-acid);
}

.mcp-step-dot:not(.mcp-step-dot--active):hover {
  background: var(--acid-soft);
}

.mcp-step-arrow {
  display: inline-flex;
  align-items: center;
  padding: 0 6px;
  color: var(--muted);
  font-weight: 800;
}

.mcp-step-panel {
  min-height: 12rem;
}

.mcp-step-enter-active,
.mcp-step-leave-active {
  transition: opacity 160ms cubic-bezier(.22, .61, .36, 1), transform 160ms cubic-bezier(.22, .61, .36, 1);
}

.mcp-step-enter-from {
  opacity: 0;
  transform: translateX(12px);
}

.mcp-step-leave-to {
  opacity: 0;
  transform: translateX(-12px);
}

.mcp-wizard-nav :deep(.btn-primary:disabled),
.mcp-wizard-nav :deep(.btn-secondary:disabled) {
  opacity: .45;
  cursor: not-allowed;
}

@media (prefers-reduced-motion: reduce) {
  .mcp-step-dot,
  .mcp-step-enter-active,
  .mcp-step-leave-active {
    transition-duration: .01ms !important;
  }
}

.text-2xs { font-size: .68rem; }
</style>
