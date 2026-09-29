<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, proxyRefs, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@/stores/authStore'
import { useDshSetupController } from '@/composables/useDshSetupController'
import { DSH_PLUGIN_INSTALL_METHODS } from '@/features/mcp/dshPlugin'
import { useClipboard } from '@/composables/useClipboard'
import { useLoginPrompt } from '@/composables/useLoginPrompt'
import { showToast } from '@/composables/useToast'
import { useDshInstallController } from '@/composables/useDshInstallController'
import { Check, Github, Package } from 'lucide-vue-next'

// 获客入口：游客可浏览第 1 步并选择安装方式；前进到命令步时弹登录。
// 登录后自动 ensure 当前用户的 DSH 专用 MCP Token（跨刷新复用同一枚，
// 服务端密封持久化）；没有身份选择步骤——配额由服务端按 token 属主
// 实时会员档位计算。登出/会话失效时立即丢弃内存 token 并退回第 1 步，
// 命令步不得残留凭证。
const { t } = useI18n()
const auth = useAuthStore()
const { requestLogin } = useLoginPrompt()
const { copy } = useClipboard()
const installCopy = proxyRefs(useDshInstallController({
  copy,
  onCopyError: () => showToast(t('mcp.copyFailed')),
}))
const controller = proxyRefs(useDshSetupController())
const installMethods = DSH_PLUGIN_INSTALL_METHODS
const stepKeys = ['dsh.wizard.stepInstall', 'dsh.wizard.stepCommand'] as const
const currentTitle = computed(() => stepKeys[controller.step])
const selectedMethod = computed(() => installMethods.find((method) => method.id === controller.selectedMethod)!)
const agentSetupPrompt = computed(() => t('dsh.wizard.agentSetupPrompt', {
  command: controller.installLine,
  method: t(selectedMethod.value.titleKey),
}))

// 前进（「下一步」按钮或前方步骤点）：游客先弹登录并留在当前步
const advance = () => {
  if (!auth.isLoggedIn) {
    requestLogin('/dsh')
    return
  }
  controller.next()
  void controller.ensure()
}
const goToStep = (index: number) => {
  if (index === controller.step) return
  if (index < controller.step) {
    controller.step = index
    return
  }
  advance()
}

onMounted(() => { if (auth.isLoggedIn) void controller.ensure() })
watch(
  () => auth.status,
  (status) => {
    if (status === 'authenticated') {
      // 页面停留期间完成登录：立即补发 Token（ensure 幂等）
      void controller.ensure()
      return
    }
    if (status === 'anonymous') {
      controller.clearToken()
      controller.step = 0
    }
  },
)
onBeforeUnmount(() => {
  installCopy.dispose()
  controller.dispose()
})
</script>

<template>
  <section class="dsh-wizard glass-card p-5 md:p-6" :aria-label="t('dsh.wizard.ariaLabel')">
    <ol class="dsh-steps flex flex-wrap items-center gap-2"><li v-for="(key, index) in stepKeys" :key="key"><button type="button" class="border px-3 py-2 text-xs font-bold" :class="controller.step === index ? 'bg-[var(--acid)]' : 'bg-card'" :aria-current="controller.step === index ? 'step' : undefined" @click="goToStep(index)">{{ index + 1 }}. {{ t(key) }}</button></li></ol>
    <p class="dsh-step-description mt-3 text-xs text-stone-500">{{ t(currentTitle + 'Description') }}</p>
    <div v-if="auth.isMember" class="dsh-quota-hint dsh-quota-hint--member mt-4 rounded border border-emerald-300 bg-emerald-50 p-3 text-xs text-emerald-800">{{ t('dsh.wizard.memberStatus') }}</div>
    <div v-else class="dsh-quota-hint mt-4 rounded border border-amber-300 bg-amber-50 p-3 text-xs text-amber-800">{{ t('dsh.wizard.vipHint') }} <RouterLink to="/membership" class="font-bold underline">{{ t('dsh.wizard.vipCta') }}</RouterLink></div>
    <div class="dsh-step-panel mt-4">
    <div v-if="controller.step === 0" class="dsh-methods grid gap-3 sm:grid-cols-2">
      <button v-for="method in installMethods" :key="method.id" type="button" class="dsh-method border p-4 text-left" :class="controller.selectedMethod === method.id ? 'border-ink bg-[var(--acid-soft)]' : 'border-stone-200 bg-card'" :aria-pressed="controller.selectedMethod === method.id" @click="controller.selectedMethod = method.id">
        <span class="dsh-method-heading">
          <component :is="method.id === 'npm' ? Package : Github" class="dsh-method-icon" aria-hidden="true" />
          <span v-if="method.recommended" class="dsh-recommended border border-ink px-2 py-0.5 text-2xs">{{ t('dsh.recommended') }}</span>
          <Check v-if="controller.selectedMethod === method.id" class="ml-auto h-5 w-5" aria-hidden="true" />
        </span>
        <span class="dsh-method-copy"><strong>{{ t(method.titleKey) }}</strong><span class="mt-2 block text-sm text-stone-500">{{ t(method.descriptionKey) }}</span></span>
        <span class="dsh-method-source font-mono text-xs text-stone-500">{{ method.id === 'npm' ? 'dsh-aigc-radar' : 'Kaixxrua/dsh-aigc-radar' }}</span>
      </button>
    </div>
    <div v-else class="dsh-command-panel space-y-3">
      <p class="text-xs font-semibold uppercase tracking-[.18em] text-stone-400">{{ t('dsh.wizard.commandLabel') }}</p>
      <template v-if="controller.phase === 'loading'"><p class="text-xs text-stone-500">{{ t('dsh.wizard.tokenCreating') }}</p></template>
      <template v-else-if="controller.phase === 'recovery'">
        <p class="rounded border border-amber-300 bg-amber-50 p-3 text-xs text-amber-800">{{ t('dsh.wizard.tokenRecovery') }}</p>
        <button type="button" class="btn-primary text-xs" @click="controller.rotate">{{ t('dsh.wizard.tokenRotate') }}</button>
      </template>
      <template v-else-if="controller.phase === 'error'"><p class="rounded bg-rose-50 p-3 text-xs text-rose-700">{{ t(controller.error) }} <button type="button" class="underline" @click="controller.ensure">{{ t('dsh.wizard.tokenRetry') }}</button></p></template>
      <template v-else-if="controller.phase === 'ready'">
        <div class="dsh-command-ready">
        <div class="dsh-command-main">
        <code class="dsh-install-command block border border-stone-700 bg-stone-900 p-3 font-mono text-xs text-white">{{ controller.installLine }}</code>
        <div class="mt-3 grid gap-2 sm:grid-cols-2">
          <button type="button" class="btn-primary text-xs" @click="installCopy.copyValue('dsh-install-line', controller.installLine)">{{ t(installCopy.copiedKey === 'dsh-install-line' ? 'mcp.copied' : 'dsh.copy') }}</button>
          <button type="button" class="btn-secondary text-xs" @click="installCopy.copyValue('dsh-agent-prompt', agentSetupPrompt)">{{ t(installCopy.copiedKey === 'dsh-agent-prompt' ? 'mcp.copied' : 'dsh.wizard.copyAgentPrompt') }}</button>
        </div>
        <p class="mt-2 text-2xs leading-4 text-amber-700">{{ t('dsh.wizard.agentPromptHint') }}</p>
        <button type="button" class="mt-2 text-xs text-stone-500 underline" @click="controller.rotate">{{ t('dsh.wizard.tokenRotate') }}</button>
        </div>
        <div class="dsh-command-notes space-y-3">
        <p class="text-xs text-stone-500">{{ t('dsh.wizard.tokenCommandNote') }}</p>
        <p class="text-xs text-amber-700">{{ t('dsh.wizard.tokenReuseNote') }}</p>
        </div>
        </div>
      </template>
    </div>
    </div>
    <div class="dsh-wizard-nav mt-6 flex items-center justify-between border-t border-stone-200 pt-4"><button type="button" class="btn-secondary text-xs" :disabled="controller.step === 0" @click="controller.previous">← {{ t('mcp.wizard.prev') }}</button><span class="text-2xs text-stone-400">{{ t('mcp.wizard.stepProgress', { current: controller.step + 1, total: 2 }) }}</span><button type="button" class="btn-primary text-xs" :disabled="controller.step === 1" @click="advance">{{ t('mcp.wizard.next') }} →</button></div>
  </section>
</template>

<style scoped>
.text-2xs { font-size: .68rem; }
.dsh-wizard { display: flex; flex-direction: column; border: 1px solid var(--ink); }
.dsh-wizard-nav { margin-top: 20px; padding-top: 16px; }
.dsh-method { display: flex; flex-direction: column; gap: 16px; min-width: 0; }
.dsh-method-heading { display: flex; align-items: center; gap: 12px; }
.dsh-method-icon { width: 28px; height: 28px; }
.dsh-method-copy strong { display: block; font-size: 18px; }
.dsh-method-source { overflow-wrap: anywhere; }
.dsh-install-command { overflow-wrap: anywhere; white-space: pre-wrap; }
.dsh-command-notes { margin-top: 16px; }
@media (min-width: 960px) { .dsh-wizard { padding: 16px; } }
@media (min-width: 960px) and (min-height: 640px) {
  .dsh-step-panel { flex: 1; min-height: 0; }
  .dsh-methods, .dsh-command-panel { height: 100%; }
  .dsh-method { justify-content: space-between; padding: clamp(16px, 2vw, 32px); }
  .dsh-method-icon { width: 36px; height: 36px; }
  .dsh-method-copy strong { font-size: clamp(20px, 2vw, 28px); }
  .dsh-method-source { padding-top: 12px; border-top: 1px solid var(--rule); }
  .dsh-command-panel { display: flex; flex-direction: column; min-height: 0; }
  .dsh-command-ready { display: grid; grid-template-columns: minmax(0, 2fr) minmax(0, 1fr); gap: 16px; flex: 1; min-height: 0; }
  .dsh-command-main { display: flex; flex-direction: column; min-height: 0; min-width: 0; }
  .dsh-command-notes { display: flex; flex-direction: column; justify-content: center; margin-top: 0; border-left: 1px solid var(--rule); padding-left: 16px; }
  .dsh-install-command { flex: 1; min-height: 0; overflow: auto; display: grid; align-content: center; padding: 24px; font-size: 14px; line-height: 1.7; }
  .dsh-wizard-nav { flex-shrink: 0; margin-top: 16px; padding-top: 12px; }
}
@media (min-width: 960px) and (max-height: 799px) {
  .dsh-wizard { padding: 12px 16px; }
  .dsh-wizard > p { margin-top: 8px; }
  .dsh-wizard > .mt-4 { margin-top: 12px; }
  .dsh-method { gap: 8px; padding: 16px; }
  .dsh-method-icon { width: 24px; height: 24px; }
  .dsh-method-copy strong { font-size: 18px; }
  .dsh-method-copy > span { margin-top: 4px; font-size: 12px; }
  .dsh-method-source { padding-top: 8px; font-size: 11px; }
  .dsh-install-command { padding: 8px 12px; font-size: 11px; line-height: 16px; }
  .dsh-command-notes p { font-size: 11px; line-height: 16px; }
  .dsh-wizard-nav { margin-top: 12px; padding-top: 8px; }
}
</style>
