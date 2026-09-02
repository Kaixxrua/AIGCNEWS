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
    <ol class="flex flex-wrap items-center gap-2"><li v-for="(key, index) in stepKeys" :key="key"><button type="button" class="border px-3 py-2 text-xs font-bold" :class="controller.step === index ? 'bg-[var(--acid)]' : 'bg-card'" @click="goToStep(index)">{{ index + 1 }}. {{ t(key) }}</button></li></ol>
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
    <div class="mt-6 flex items-center justify-between border-t border-stone-200 pt-4"><button type="button" class="btn-secondary text-xs" :disabled="controller.step === 0" @click="controller.previous">← {{ t('mcp.wizard.prev') }}</button><span class="text-2xs text-stone-400">{{ t('mcp.wizard.stepProgress', { current: controller.step + 1, total: 2 }) }}</span><button type="button" class="btn-primary text-xs" :disabled="controller.step === 1" @click="advance">{{ t('mcp.wizard.next') }} →</button></div>
  </section>
</template>

<style scoped>.text-2xs { font-size: .68rem; } .dsh-wizard { border: 1px solid var(--ink); }</style>
