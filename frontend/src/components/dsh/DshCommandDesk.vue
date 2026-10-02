<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, proxyRefs, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { Github, Package } from 'lucide-vue-next'
import { useAuthStore } from '@/stores/authStore'
import { buildDshInstallLine, useDshSetupController } from '@/composables/useDshSetupController'
import { useDshInstallController } from '@/composables/useDshInstallController'
import { DSH_PLUGIN_INSTALL_METHODS, type DshPluginInstallMethodId } from '@/features/mcp/dshPlugin'
import { COMMAND_TOKEN_SLOT } from '@/features/mcp/commandPreview'
import { useClipboard } from '@/composables/useClipboard'
import { useLoginPrompt } from '@/composables/useLoginPrompt'
import { showToast } from '@/composables/useToast'
import { vIndicator } from '@/motion/indicator'
import { vMorph } from '@/motion/morph'
import { vSwap } from '@/motion/swap'
import RollText from '@/motion/RollText.vue'
import CommandPreview from '@/components/mcp/CommandPreview.vue'

/**
 * /dsh 桌面版的接入命令台：安装方式缩成两枚标签，命令模板打开就在首屏，Token 处是占位。
 * 游客点复制先登录；登录后自动取回账号的 DSH 专用 Token（ensure 幂等，跨刷新复用同一枚），
 * 带 Token 的命令只进剪贴板，页面上不出现。登出或会话失效立即丢弃内存里的 Token。
 * 窄屏仍用两步向导（DshSetupWizard）。
 */
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
const selectedMethod = computed(() => installMethods.find((method) => method.id === controller.selectedMethod)!)

// 新命令沿切换方向滑入：切到右边的标签，从右边进来。
const direction = ref(1)
const methodIndex = (id: DshPluginInstallMethodId) => installMethods.findIndex((method) => method.id === id)
watch(() => controller.selectedMethod, (next, previous) => { direction.value = methodIndex(next) < methodIndex(previous) ? -1 : 1 })

const previewCommand = computed(() => buildDshInstallLine(controller.command, COMMAND_TOKEN_SLOT))
const agentSetupPrompt = computed(() => t('dsh.wizard.agentSetupPrompt', {
  command: controller.installLine,
  method: t(selectedMethod.value.titleKey),
}))

// 右栏：游客先登录；登录后取 Token 中；就绪可复制；旧版 Token 需重新生成；出错可重试。
const deskState = computed(() => {
  if (!auth.isLoggedIn) return 'guest'
  if (controller.phase === 'ready' && controller.installLine) return 'ready'
  if (controller.phase === 'recovery' || controller.phase === 'error') return controller.phase
  return 'loading'
})

onMounted(() => { if (auth.isLoggedIn) void controller.ensure() })
watch(
  () => auth.status,
  (status) => {
    // 页面停留期间完成登录：立即补发 Token（ensure 幂等）
    if (status === 'authenticated') void controller.ensure()
    if (status === 'anonymous') controller.clearToken()
  },
)
onBeforeUnmount(() => {
  installCopy.dispose()
  controller.dispose()
})
</script>

<template>
  <section class="dsh-desk" :aria-label="t('dsh.desk.ariaLabel')">
    <div class="dsh-desk-head">
      <p class="dsh-desk-label"><span class="dsh-desk-num" aria-hidden="true">1</span>{{ t('dsh.wizard.stepInstall') }}</p>
      <div v-indicator="{ active: '[aria-pressed=true]' }" class="dsh-desk-tabs" role="group" :aria-label="t('dsh.wizard.stepInstall')">
        <button v-for="method in installMethods" :key="method.id" type="button" class="dsh-desk-tab" :aria-pressed="controller.selectedMethod === method.id" @click="controller.selectedMethod = method.id">
          <component :is="method.id === 'npm' ? Package : Github" aria-hidden="true" />{{ t(method.titleKey) }}<span v-if="method.recommended" class="dsh-desk-recommended">{{ t('dsh.recommended') }}</span>
        </button>
      </div>
      <p v-swap="{ key: controller.selectedMethod, x: direction * 10, y: 0 }" class="dsh-desk-method">{{ t(selectedMethod.descriptionKey) }}</p>
    </div>
    <CommandPreview class="dsh-desk-term" :command="previewCommand" :filled="deskState === 'ready'" :swap-key="controller.selectedMethod" :direction="direction" />
    <p v-if="auth.isMember" class="dsh-quota-hint dsh-quota-hint--member">{{ t('dsh.wizard.memberStatus') }}</p>
    <p v-else class="dsh-quota-hint">{{ t('dsh.wizard.vipHint') }} <RouterLink to="/membership">{{ t('dsh.wizard.vipCta') }}</RouterLink></p>

    <div class="dsh-desk-side" :class="`dsh-desk-side--${deskState}`" aria-live="polite">
      <p class="dsh-desk-label"><span class="dsh-desk-num" aria-hidden="true">2</span>{{ t('dsh.wizard.stepCommand') }}</p>
      <div v-morph="deskState" v-swap="{ key: deskState, y: 8 }" class="dsh-desk-side-body">
        <template v-if="deskState === 'ready'">
          <button type="button" class="btn-primary" @click="installCopy.copyValue('dsh-install-line', controller.installLine)"><RollText :value="t(installCopy.copiedKey === 'dsh-install-line' ? 'mcp.copied' : 'dsh.copy')" /></button>
          <button type="button" class="btn-secondary" :title="t('dsh.wizard.agentPromptHint')" @click="installCopy.copyValue('dsh-agent-prompt', agentSetupPrompt)"><RollText :value="t(installCopy.copiedKey === 'dsh-agent-prompt' ? 'mcp.copied' : 'dsh.wizard.copyAgentPrompt')" /></button>
          <p class="dsh-desk-note">{{ t('dsh.wizard.tokenCommandNote') }}</p>
          <p class="dsh-desk-note dsh-desk-note--warn">{{ t('dsh.wizard.tokenReuseNote') }}</p>
          <button type="button" class="dsh-desk-link" @click="controller.rotate">{{ t('dsh.wizard.tokenRotate') }}</button>
        </template>
        <template v-else-if="deskState === 'recovery'">
          <p class="dsh-desk-note dsh-desk-note--warn">{{ t('dsh.wizard.tokenRecovery') }}</p>
          <button type="button" class="btn-primary" @click="controller.rotate">{{ t('dsh.wizard.tokenRotate') }}</button>
        </template>
        <template v-else-if="deskState === 'error'">
          <p class="dsh-desk-error">{{ t(controller.error) }}</p>
          <button type="button" class="btn-primary" @click="controller.ensure">{{ t('dsh.wizard.tokenRetry') }}</button>
        </template>
        <template v-else>
          <p class="dsh-desk-summary">{{ t('dsh.desk.summary') }}</p>
          <button v-if="deskState === 'guest'" type="button" class="btn-primary" @click="requestLogin('/dsh')">{{ t('mcp.desk.loginToCopy') }}</button>
          <button v-else type="button" class="btn-primary" disabled>{{ t('dsh.wizard.tokenCreating') }}</button>
          <p v-if="deskState === 'guest'" class="dsh-desk-note">{{ t('dsh.desk.guestHint') }}</p>
          <p class="dsh-desk-note">{{ t('mcp.desk.tokenNote') }}</p>
        </template>
      </div>
    </div>
  </section>
</template>
