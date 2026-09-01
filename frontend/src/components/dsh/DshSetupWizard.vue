<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, proxyRefs } from 'vue'
import { RouterLink } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@/stores/authStore'
import { useDshSetupController } from '@/composables/useDshSetupController'
import { DSH_PLUGIN_INSTALL_METHODS } from '@/features/mcp/dshPlugin'
import { useClipboard } from '@/composables/useClipboard'
import { showToast } from '@/composables/useToast'
import { useDshInstallController } from '@/composables/useDshInstallController'

// 前置条件：本组件只在已认证状态下由 DshView 挂载（路由 meta.requiresAuth +
// 视图层 watcher 兜底）。挂载即 ensure 当前用户的 DSH 专用 MCP Token；
// 没有身份选择步骤——配额由服务端按 token 属主实时会员档位计算。
const { t } = useI18n()
const auth = useAuthStore()
const { copy } = useClipboard()
const installCopy = proxyRefs(useDshInstallController({
  copy,
  onCopyError: () => showToast(t('mcp.copyFailed')),
}))
const controller = proxyRefs(useDshSetupController())
const installMethods = DSH_PLUGIN_INSTALL_METHODS
const stepKeys = ['dsh.wizard.stepInstall', 'dsh.wizard.stepCommand'] as const
const currentTitle = computed(() => stepKeys[controller.step])
onMounted(() => { void controller.ensure() })
onBeforeUnmount(() => {
  installCopy.dispose()
  controller.dispose()
})
</script>

<template>
  <section class="dsh-wizard glass-card p-5 md:p-6" :aria-label="t('dsh.wizard.ariaLabel')">
    <ol class="flex flex-wrap items-center gap-2"><li v-for="(key, index) in stepKeys" :key="key"><button type="button" class="border px-3 py-2 text-xs font-bold" :class="controller.step === index ? 'bg-[var(--acid)]' : 'bg-card'" @click="index <= controller.step && (controller.step = index)">{{ index + 1 }}. {{ t(key) }}</button></li></ol>
    <p class="mt-3 text-xs text-stone-500">{{ t(currentTitle + 'Description') }}</p>
    <div v-if="auth.isMember" class="mt-4 rounded border border-emerald-300 bg-emerald-50 p-3 text-xs text-emerald-800">{{ t('dsh.wizard.memberStatus') }}</div>
    <div v-else class="mt-4 rounded border border-amber-300 bg-amber-50 p-3 text-xs text-amber-800">{{ t('dsh.wizard.vipHint') }} <RouterLink to="/membership" class="font-bold underline">{{ t('dsh.wizard.vipCta') }}</RouterLink></div>
    <div v-if="controller.step === 0" class="mt-5 grid gap-3">
      <button v-for="method in installMethods" :key="method.id" type="button" class="border p-4 text-left" :class="controller.selectedMethod === method.id ? 'border-ink bg-[var(--acid-soft)]' : 'border-stone-200 bg-card'" @click="controller.selectedMethod = method.id"><strong>{{ t(method.titleKey) }}</strong><span v-if="method.recommended" class="ml-2 border border-ink px-2 py-0.5 text-2xs">{{ t('dsh.recommended') }}</span><span class="mt-1 block text-xs text-stone-500">{{ t(method.descriptionKey) }}</span></button>
    </div>
    <div v-else class="mt-5 space-y-4">
      <p class="text-xs font-semibold uppercase tracking-[.18em] text-stone-400">{{ t('dsh.wizard.commandLabel') }}</p>
      <template v-if="controller.phase === 'loading'"><p class="text-xs text-stone-500">{{ t('dsh.wizard.tokenCreating') }}</p></template>
      <template v-else-if="controller.phase === 'recovery'">
        <p class="rounded border border-amber-300 bg-amber-50 p-3 text-xs text-amber-800">{{ t('dsh.wizard.tokenRecovery') }}</p>
        <button type="button" class="btn-primary text-xs" @click="controller.rotate">{{ t('dsh.wizard.tokenRotate') }}</button>
      </template>
      <template v-else-if="controller.phase === 'error'"><p class="rounded bg-rose-50 p-3 text-xs text-rose-700">{{ t(controller.error) }} <button type="button" class="underline" @click="controller.ensure">{{ t('dsh.wizard.tokenRetry') }}</button></p></template>
      <template v-else-if="controller.phase === 'ready'">
        <code class="block overflow-x-auto whitespace-nowrap border border-stone-700 bg-stone-900 p-3 font-mono text-xs text-white">{{ controller.installLine }}</code>
        <div class="flex flex-wrap items-center gap-3">
          <button type="button" class="btn-primary text-xs" @click="installCopy.copyValue('dsh-install-line', controller.installLine)">{{ t(installCopy.copiedKey === 'dsh-install-line' ? 'mcp.copied' : 'dsh.copy') }}</button>
          <button type="button" class="text-xs text-stone-500 underline" @click="controller.rotate">{{ t('dsh.wizard.tokenRotate') }}</button>
        </div>
        <p class="text-xs text-stone-500">{{ t('dsh.wizard.tokenCommandNote') }}</p>
        <p class="text-xs text-amber-700">{{ t('dsh.wizard.tokenReuseNote') }}</p>
      </template>
    </div>
    <div class="mt-6 flex items-center justify-between border-t border-stone-200 pt-4"><button type="button" class="btn-secondary text-xs" :disabled="controller.step === 0" @click="controller.previous">← {{ t('mcp.wizard.prev') }}</button><span class="text-2xs text-stone-400">{{ t('mcp.wizard.stepProgress', { current: controller.step + 1, total: 2 }) }}</span><button type="button" class="btn-primary text-xs" :disabled="controller.step === 1" @click="controller.next">{{ t('mcp.wizard.next') }} →</button></div>
  </section>
</template>

<style scoped>.text-2xs { font-size: .68rem; } .dsh-wizard { border: 1px solid var(--ink); }</style>
