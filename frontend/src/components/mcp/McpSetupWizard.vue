<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import type { McpConnectController } from '@/composables/useMcpConnectController'
import { mcpClientOptions, mcpShellOptions, mcpWizardStepTitleKeys, type McpClientOption } from '@/features/mcp/mcpClientCatalog'
import { resolveMcpFeedback } from '@/features/mcp/mcpFeedback'
import { clientConfigTarget as configTargetOf, clientDescription, setupResultDescription as resultDescriptionOf, setupScopeLabel as scopeLabelOf, setupTargetDescription as targetDescriptionOf } from '@/features/mcp/mcpSetupTarget'
import { installMcpOAuthSetupMessages } from '@/i18n/locales/mcpOAuthSetup'
import { vIndicator } from '@/motion/indicator'
import { vMorph } from '@/motion/morph'
import { vSwap } from '@/motion/swap'
import McpConnectionStatus from './McpConnectionStatus.vue'

const props = defineProps<{
  controller: McpConnectController
}>()

installMcpOAuthSetupMessages()
const { t } = useI18n()

const {
  authMode,
  authModeFor,
  clientDisplayLabel,
  clientOption,
  connection,
  copiedKey,
  copyAgentSetupPrompt,
  copyGeneratedCommand,
  creating,
  endpointUrl,
  endpointWarningKey,
  isLoggedIn,
  normalizedEndpoint,
  requestLogin,
  selectedClient,
  selectedShell,
  setAuthMode,
  setupError,
  startSetup,
  testing,
  testMessage,
  testPhases,
  testPublicHandshake,
  transientCommand,
} = props.controller

const stepTitleKeys = mcpWizardStepTitleKeys
const stepDescriptionKeys = computed(() => [
  'mcp.wizard.stepClientDescription',
  authMode.value === 'oauth' ? 'mcpOAuthSetup.stepDescription' : 'mcpAutoCommand.description',
  'mcp.wizard.stepVerifyDescription',
] as const)

const currentStep = ref(0)
// 步骤面板沿前进方向滑入：往后退时从左边进来。
const stepDir = ref(1)
const rootEl = ref<HTMLElement | null>(null)
const isFirst = computed(() => currentStep.value === 0)
const isLast = computed(() => currentStep.value === stepTitleKeys.length - 1)

const shellOptions = mcpShellOptions
const clientOptions = mcpClientOptions
const setupScopeLabel = computed(() => scopeLabelOf(clientOption.value, t, authMode.value))
const clientConfigTarget = (option: McpClientOption) => configTargetOf(option, t)
const setupTargetDescription = computed(() => targetDescriptionOf(clientOption.value, selectedShell.value, t, authMode.value))
const setupResultDescription = computed(() => resultDescriptionOf(clientOption.value, t, authMode.value))
const setupErrorDisplay = computed(() => resolveMcpFeedback(setupError.value, t))
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
  // 游客可自由浏览第 1 步并选择客户端/终端；浏览器授权版命令里没有 Token，游客也能往后走，到授权页再登录。
  // 手动 Token 版前进到命令与验证步须先登录（Token 在登录后才可签发）。返回已看过的步骤不受限。
  if (index > currentStep.value && authMode.value === 'token' && !isLoggedIn.value) {
    await requestLogin()
    return
  }
  stepDir.value = index > currentStep.value ? 1 : -1
  currentStep.value = index
  await scrollToWizardTop()
  if (index === 1 && authMode.value === 'token' && !transientCommand.value && !creating.value && !endpointWarningKey.value) {
    void startSetup()
  }
}
const goPrev = () => goTo(Math.max(0, currentStep.value - 1))
const goNext = () => goTo(Math.min(stepTitleKeys.length - 1, currentStep.value + 1))
</script>

<template>
  <section ref="rootEl" class="mcp-wizard glass-card scroll-mt-4 p-5 md:p-6" :style="{ '--mcp-step-dir': stepDir }" :aria-label="t('mcp.wizard.ariaLabel')">
    <ol v-indicator="{ active: '.mcp-step-dot--active', mark: false, pop: true }" class="mcp-wizard-steps flex list-none flex-wrap items-stretch gap-y-2 p-0">
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
        <div v-if="currentStep === 0" class="mcp-client-layout">
          <div class="mcp-client-list">
          <p class="text-xs font-semibold uppercase tracking-[0.18em] text-stone-400">{{ t('mcp.chooseClient') }}</p>
          <div v-indicator="{ active: '.mcp-choice--active', mark: false, pop: true }" class="mcp-client-grid mt-3 grid grid-cols-2 gap-2 sm:grid-cols-3">
            <button v-for="client in clientOptions" :key="client.id" type="button" class="mcp-choice rounded-[18px] border p-3 text-left" :class="selectedClient === client.id ? 'mcp-choice--active' : 'border-stone-200 bg-card'" :aria-pressed="selectedClient === client.id" :title="clientDescription(client, t, authModeFor(client))" @click="selectedClient = client.id">
              <span class="text-sm font-semibold text-stone-800">{{ clientDisplayLabel(client) }}</span>
              <span class="mcp-client-caption text-stone-500">{{ clientDescription(client, t, authModeFor(client)) }}</span>
            </button>
          </div>
          </div>
          <div class="mcp-client-settings">
          <div class="mcp-client-detail mt-3 rounded-xl border border-stone-200 p-3" aria-live="polite">
            <span class="text-2xs font-semibold text-stone-600">{{ setupScopeLabel }}</span>
            <p class="mt-1 text-xs leading-5 text-stone-500">{{ clientDescription(clientOption, t, authMode) }}</p>
          </div>
          <div class="mcp-terminal">
          <p class="mt-5 text-sm font-semibold text-stone-700">{{ t('mcp.terminal') }}</p>
          <div v-indicator="{ active: '.mcp-choice--active', mark: false, pop: true }" class="mcp-shell-options mt-2 flex flex-wrap gap-2"><button v-for="shell in shellOptions" :key="shell.id" type="button" class="mcp-choice rounded-full border px-3 py-2 text-xs" :class="selectedShell === shell.id ? 'mcp-choice--active' : 'border-stone-200 bg-card text-stone-600'" :aria-pressed="selectedShell === shell.id" @click="selectedShell = shell.id">{{ shell.labelKey ? t(shell.labelKey) : shell.label }}</button></div>
          </div>
          </div>
        </div>

        <div v-else-if="currentStep === 1" v-morph="authMode" v-swap="{ key: authMode, y: 8 }" class="mcp-command-panel">
          <p class="text-xs font-semibold uppercase tracking-[0.18em] text-stone-400">{{ t(authMode === 'oauth' ? 'mcpOAuthSetup.title' : 'mcpAutoCommand.label') }}</p>
          <div class="mt-4 rounded-2xl border border-stone-200 bg-card/75 p-4"><div class="flex flex-wrap items-center gap-2"><span class="rounded-full bg-stone-100 px-2.5 py-1 text-2xs font-semibold text-stone-600">{{ setupScopeLabel }}</span><span class="text-xs font-semibold text-stone-700">{{ clientConfigTarget(clientOption) }}</span></div><p class="mt-2 text-xs leading-5 text-stone-500">{{ setupTargetDescription }}</p></div>
          <div v-if="authMode === 'oauth'" class="mt-4 rounded-2xl border border-stone-200 bg-card/75 p-4">
            <p class="text-xs leading-5 text-stone-600">{{ setupResultDescription }}</p>
            <div class="mcp-command-actions mt-3 grid gap-2 sm:grid-cols-2">
              <button type="button" class="btn-primary w-full justify-center text-xs" data-wizard-action="copy-oauth" @click="copyGeneratedCommand">{{ t(copiedKey === 'command' ? 'mcp.copiedClipboard' : 'mcpAutoCommand.copy') }}</button>
              <button type="button" class="btn-secondary w-full justify-center text-xs" @click="copyAgentSetupPrompt">{{ t(copiedKey === 'agent-prompt' ? 'mcp.copiedClipboard' : 'mcpAutoCommand.copyAgentPrompt') }}</button>
            </div>
            <p class="mt-2 text-2xs leading-4 text-stone-500">{{ t('mcpOAuthSetup.agentPromptHint') }}</p>
            <p v-if="setupErrorDisplay" class="mt-2 text-xs text-rose-700">{{ setupErrorDisplay }}</p>
          </div>
          <div v-else-if="creating" class="mt-4 rounded-2xl bg-stone-50 px-4 py-3 text-xs text-stone-600">{{ t('mcpAutoCommand.creating') }}</div>
          <div v-else-if="transientCommand" class="mt-4 rounded-2xl border border-amber-300 bg-amber-50 p-4">
            <p class="text-sm font-semibold text-amber-900">{{ t('mcpAutoCommand.ready') }}</p>
            <p class="mt-1 text-xs font-semibold leading-5 text-amber-800">{{ t('mcp.bearerWarningDetail') }}</p>
            <p class="mt-2 text-xs leading-5 text-amber-700">{{ t('mcp.hiddenConfig', { result: setupResultDescription }) }}</p>
            <div class="mcp-command-actions mt-3 grid gap-2 sm:grid-cols-2">
              <button type="button" class="btn-primary w-full justify-center text-xs" @click="copyGeneratedCommand">{{ t(copiedKey === 'command' ? 'mcp.copiedClipboard' : 'mcpAutoCommand.copy') }}</button>
              <button type="button" class="btn-secondary w-full justify-center text-xs" @click="copyAgentSetupPrompt">{{ t(copiedKey === 'agent-prompt' ? 'mcp.copiedClipboard' : 'mcpAutoCommand.copyAgentPrompt') }}</button>
            </div>
            <p class="mt-2 text-2xs leading-4 text-amber-700">{{ t('mcpAutoCommand.agentPromptHint') }}</p>
            <McpConnectionStatus class="mt-3" :connection="connection" :client="clientDisplayLabel(clientOption)" />
          </div>
          <div v-else-if="setupErrorDisplay" class="mt-4 rounded-2xl bg-rose-50 px-4 py-3 text-xs text-rose-700"><p>{{ setupErrorDisplay }}</p><button type="button" class="mt-2 underline" @click="startSetup">{{ t('common.retry') }}</button></div>
          <div v-else class="mt-4 rounded-2xl border border-stone-200 bg-card/75 p-4">
            <button v-if="isLoggedIn" type="button" class="btn-primary w-full justify-center text-xs" data-wizard-action="generate" @click="startSetup">{{ t('mcp.desk.generate') }}</button>
            <button v-else type="button" class="btn-primary w-full justify-center text-xs" @click="requestLogin">{{ t('mcp.desk.loginToCopy') }}</button>
            <p class="mt-2 text-2xs leading-4 text-stone-500">{{ t(isLoggedIn ? 'mcp.desk.generateHint' : 'mcp.desk.guestHint') }}</p>
          </div>
          <button v-if="clientOption.oauth" type="button" class="mcp-auth-switch mt-3 self-start text-xs font-semibold text-stone-700 underline decoration-dashed underline-offset-4" :data-wizard-action="authMode === 'oauth' ? 'use-token' : 'use-oauth'" @click="setAuthMode(authMode === 'oauth' ? 'token' : 'oauth')">{{ t(authMode === 'oauth' ? 'mcpOAuthSetup.useToken' : 'mcpOAuthSetup.useOAuth') }}</button>
        </div>

        <div v-else-if="currentStep === 2" class="mcp-verify-panel">
          <McpConnectionStatus v-if="transientCommand" class="mcp-verify-connection mb-4 rounded-2xl border border-stone-200 bg-card/75 p-4" :connection="connection" :client="clientDisplayLabel(clientOption)" :divider="false" />
          <p class="text-xs font-semibold uppercase tracking-[0.18em] text-stone-400">{{ t('mcp.publicEndpoint') }}</p>
          <div class="mt-3 rounded-2xl border border-stone-200 bg-stone-50/80 px-3 py-2 font-mono text-xs text-stone-700">{{ normalizedEndpoint }}</div>
          <div class="mt-3 flex flex-col gap-2 sm:flex-row"><input v-model.trim="endpointUrl" class="input min-w-0 flex-1 font-mono text-xs" :aria-label="t('mcp.endpointAria')" /><button type="button" class="btn-secondary justify-center text-xs" :disabled="testing || Boolean(endpointWarning)" @click="testPublicHandshake">{{ t(testing ? 'mcp.testing' : 'mcp.publicHandshake') }}</button></div>
          <p v-if="endpointWarning" class="mt-2 text-xs text-rose-700">{{ endpointWarning }}</p>
          <p v-if="testMessageDisplay" class="mt-3 text-xs text-stone-500">{{ testMessageDisplay }}</p>
          <div class="mcp-handshake-phases mt-3 grid grid-cols-1 gap-2 sm:grid-cols-3"><div v-for="phase in testPhases" :key="phase.label" class="mcp-handshake-phase rounded-xl border border-stone-200 bg-card p-2"><p class="text-2xs text-stone-700">{{ t(`mcp.phase.${phase.descriptionKey}`) }}</p><p class="mt-1 text-2xs" :class="phase.status === 'success' ? 'text-emerald-600' : phase.status === 'error' ? 'text-rose-600' : 'text-stone-400'">{{ phase.detail ? resolveMcpFeedback(phase.detail, t) : t(`mcp.phaseStatus.${phase.status}`) }}</p></div></div>
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
.mcp-wizard { display: flex; flex-direction: column; }
.mcp-client-grid .mcp-choice { min-height: 44px; }
.mcp-client-caption { display: none; }
.mcp-client-detail { min-height: 72px; }
.mcp-command-panel { min-width: 0; }

@media (min-width: 960px) {
  .mcp-wizard { padding: 16px; }
  .mcp-client-grid .mcp-choice { padding: 8px 12px; }
  .mcp-client-detail { min-height: 0; padding: 8px 12px; }
  .mcp-client-detail + p { margin-top: 12px; }
  .mcp-step-panel { margin-top: 12px; }
  .mcp-wizard-nav { margin-top: 12px; padding-top: 8px; }
  .mcp-command-panel > * + * { margin-top: 12px; }
  .mcp-command-panel > div { padding: 12px; }
}

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
  min-height: 0;
}

@media (min-width: 960px) and (min-height: 640px) {
  .mcp-wizard-step { flex: 1; }
  .mcp-step-dot { width: 100%; justify-content: center; }
  .mcp-step-panel { flex: 1; }
  .mcp-client-layout {
    display: grid;
    grid-template-columns: minmax(0, 3fr) minmax(200px, 1fr);
    grid-template-rows: minmax(0, 1fr);
    gap: 16px;
    height: 100%;
  }
  .mcp-client-list { display: flex; flex-direction: column; min-height: 0; }
  .mcp-client-grid { flex: 1; min-height: 0; grid-template-rows: repeat(3, minmax(0, 1fr)); }
  .mcp-client-grid .mcp-choice { display: flex; flex-direction: column; justify-content: center; gap: 8px; padding: 12px 16px; min-height: 0; }
  .mcp-client-settings { display: grid; grid-template-rows: minmax(0, 1fr) auto; gap: 12px; min-width: 0; min-height: 0; }
  .mcp-client-detail { margin-top: 0; display: flex; flex-direction: column; justify-content: center; padding: 16px; }
  .mcp-terminal > p { margin-top: 0; font-size: 12px; }
  .mcp-shell-options { display: grid; grid-template-columns: minmax(0, 1fr); }
  .mcp-command-panel { display: flex; flex-direction: column; height: 100%; }
  .mcp-verify-panel { display: flex; flex-direction: column; height: 100%; }
  .mcp-handshake-phases { flex: 1; min-height: 0; }
  .mcp-handshake-phase { display: flex; flex-direction: column; justify-content: center; padding: 24px; }
  .mcp-handshake-phase > p { font-size: 14px; }
  .mcp-wizard-nav { flex-shrink: 0; }
}

@media (min-width: 960px) and (max-height: 799px) {
  .mcp-wizard { padding: 12px 16px; }
  .mcp-wizard > p { margin-top: 8px; }
  .mcp-step-panel { margin-top: 8px; }
  .mcp-client-grid { margin-top: 8px; }
  .mcp-client-grid .mcp-choice { padding: 8px 12px; }
  .mcp-client-detail { padding: 8px 12px; }
  .mcp-shell-options { display: flex; gap: 6px; }
  .mcp-shell-options .mcp-choice { flex: 1 1 70px; padding: 6px 8px; font-size: 11px; }
  .mcp-wizard-nav { margin-top: 8px; padding-top: 8px; }
  .mcp-command-panel > * + * { margin-top: 8px; }
  .mcp-command-panel > div { padding: 8px; }
  .mcp-command-panel > div > p { margin-top: 4px; font-size: 11px; line-height: 16px; }
}

@media (min-width: 960px) and (min-height: 800px) {
  .mcp-client-caption { display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; font-size: 11px; line-height: 1.5; }
}

.mcp-step-enter-active,
.mcp-step-leave-active {
  transition: opacity 160ms cubic-bezier(.22, .61, .36, 1), transform 160ms cubic-bezier(.22, .61, .36, 1);
}

.mcp-step-enter-from {
  opacity: 0;
  transform: translateX(calc(12px * var(--mcp-step-dir, 1)));
}

.mcp-step-leave-to {
  opacity: 0;
  transform: translateX(calc(-12px * var(--mcp-step-dir, 1)));
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
