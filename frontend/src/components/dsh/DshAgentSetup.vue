<script setup lang="ts">
import { computed, onBeforeUnmount, ref, useId } from 'vue'
import { useI18n } from 'vue-i18n'
import { Bot, Check, ChevronDown, ClipboardCopy, Copy, MessageSquareText } from 'lucide-vue-next'
import { useAuthStore } from '@/stores/authStore'
import { useLoginPrompt } from '@/composables/useLoginPrompt'
import { copySensitiveToClipboard } from '@/composables/useClipboard'
import { useCopyNotice } from '@/composables/useCopyNotice'
import type { DshSetupController } from '@/composables/useDshSetupController'
import { useMcpInstallCode } from '@/composables/useMcpInstallCode'
import { showToast } from '@/composables/useToast'
import { buildDshAgentPrompt } from '@/features/mcp/agentSetupPrompt'
import { COMMAND_TOKEN_SLOT } from '@/features/mcp/commandPreview'
import { installAgentSetupMessages } from '@/i18n/locales/agentSetup'
import { fold, unfold } from '@/motion/fold'
import { vMorph } from '@/motion/morph'
import { vSwap } from '@/motion/swap'
import RollText from '@/motion/RollText.vue'
import AgentStoryboard from '@/components/mcp/AgentStoryboard.vue'
import CommandPreview from '@/components/mcp/CommandPreview.vue'
import McpConnectionStatus from '@/components/mcp/McpConnectionStatus.vue'
import '@/components/mcp/agent-setup.css'

/**
 * /dsh 的主卡：一颗「复制给 Agent 的配置提示词」，Agent 装插件（npm 优先、GitHub 兜底），用一次性安装码换来账号的
 * DSH 专用 Token 写进 dsh web profile。提示词只带安装码、不带 Token；码要登录才能签，所以游客先登录。
 * 页面先由控制器确认 DSH Token 就绪（ensure 幂等，旧版 Token 要先重新生成），再预取 dsh 用途的安装码；带码的提示词只进
 * 安全剪贴板，预览里是占位，复制后换一枚新码。复制后盯着这枚 Token 等 dsh 第一次搜索。
 */
installAgentSetupMessages()

const props = defineProps<{ controller: DshSetupController }>()

const { t, locale } = useI18n()
const auth = useAuthStore()
const { requestLogin } = useLoginPrompt()
const { phase, token, error, connection, ensure, rotate } = props.controller
const notice = useCopyNotice({ onError: () => showToast(t('mcp.copyFailed')) })
const copied = computed(() => notice.copiedKey.value === 'dsh-agent-prompt')
const previewOpen = ref(false)
const previewId = `dsh-agent-prompt-${useId()}`
const tokenReady = computed(() => auth.isLoggedIn && phase.value === 'ready' && Boolean(token.value))
const installCode = useMcpInstallCode({ purpose: 'dsh', enabled: tokenReady })
const installCodeSlot = { empty: 'agentSetup.installCode.slot', filled: 'agentSetup.installCode.slotFilled' }
const dshPageUrl = () => `${window.location.origin}/dsh`

// 游客先登录；登录后取 Token、签安装码中；都就绪可复制；旧版 Token 需重新生成；出错可重试。
const state = computed(() => {
  if (!auth.isLoggedIn) return 'guest'
  if (tokenReady.value) {
    if (installCode.status.value === 'ready') return 'ready'
    if (installCode.status.value === 'error') return 'code-error'
    return 'loading'
  }
  if (phase.value === 'recovery' || phase.value === 'error') return phase.value
  return 'loading'
})
const preview = computed(() => buildDshAgentPrompt(locale.value, COMMAND_TOKEN_SLOT, dshPageUrl()))

const copyPrompt = async () => {
  // 码一般早已备好，同步拼进提示词；后台标签页里换新的定时器被推迟、码刚过期时，先补签一枚再复制。
  let code = installCode.current()
  if (!code && await installCode.refresh()) code = installCode.current()
  if (!code) return
  const text = buildDshAgentPrompt(locale.value, code, dshPageUrl())
  if (await notice.copy('dsh-agent-prompt', () => copySensitiveToClipboard(text))) {
    installCode.rotate()
    // 复制了提示词，接下来几分钟最可能连上：让连接检测重新勤快地查。
    connection.nudge()
  }
}

const steps = computed(() => [
  { id: 'copy', icon: ClipboardCopy, title: t('agentSetup.dsh.steps.copy.title'), body: t('agentSetup.dsh.steps.copy.body') },
  { id: 'paste', icon: Bot, title: t('agentSetup.dsh.steps.paste.title'), body: t('agentSetup.dsh.steps.paste.body') },
  { id: 'ask', icon: MessageSquareText, title: t('agentSetup.dsh.steps.ask.title'), body: t('agentSetup.dsh.steps.ask.body') },
])

onBeforeUnmount(() => {
  notice.dispose()
  installCode.dispose()
})
</script>

<template>
  <section class="agent-setup agent-setup--dsh dsh-hero" :aria-label="t('agentSetup.copyPrompt')">
    <p class="agent-setup-kicker dsh-eyebrow">{{ t('dsh.eyebrow') }}</p>
    <p class="agent-setup-lede">{{ t('agentSetup.dsh.lede') }}</p>
    <div v-morph="state" class="agent-setup-actions">
      <div v-swap="{ key: state, y: 6 }" class="agent-setup-face" aria-live="polite">
        <button v-if="state === 'guest'" type="button" class="agent-setup-cta" @click="requestLogin('/dsh')">
          <Copy class="agent-setup-cta-icon" aria-hidden="true" />{{ t('agentSetup.loginToCopy') }}
        </button>
        <button v-else-if="state === 'ready'" type="button" class="agent-setup-cta" :class="{ 'agent-setup-cta--copied': copied }" @click="copyPrompt">
          <component :is="copied ? Check : Copy" class="agent-setup-cta-icon" aria-hidden="true" />
          <RollText :value="t(copied ? 'agentSetup.copied' : 'agentSetup.copyPrompt')" />
        </button>
        <template v-else-if="state === 'recovery'">
          <p class="agent-setup-warn">{{ t('dsh.wizard.tokenRecovery') }}</p>
          <button type="button" class="agent-setup-cta" @click="rotate">{{ t('dsh.wizard.tokenRotate') }}</button>
        </template>
        <template v-else-if="state === 'error'">
          <p class="agent-setup-error">{{ t(error) }}</p>
          <button type="button" class="agent-setup-cta" @click="ensure">{{ t('dsh.wizard.tokenRetry') }}</button>
        </template>
        <template v-else-if="state === 'code-error'">
          <p class="agent-setup-error">{{ t('agentSetup.installCode.failed') }}</p>
          <button type="button" class="agent-setup-cta" @click="installCode.refresh">{{ t('dsh.wizard.tokenRetry') }}</button>
        </template>
        <button v-else type="button" class="agent-setup-cta" disabled>{{ t('dsh.wizard.tokenCreating') }}</button>
      </div>
      <button type="button" class="agent-setup-toggle" :aria-expanded="previewOpen" :aria-controls="previewId" @click="previewOpen = !previewOpen">
        <ChevronDown class="agent-setup-toggle-icon" aria-hidden="true" />{{ t(previewOpen ? 'agentSetup.previewHide' : 'agentSetup.previewShow') }}
      </button>
    </div>
    <Transition @enter="unfold" @leave="fold">
      <div v-show="previewOpen" :id="previewId" role="region" :aria-label="t('agentSetup.previewLabel')">
        <CommandPreview class="agent-setup-preview" :command="preview" :filled="state === 'ready'" :slot-keys="installCodeSlot" swap-key="dsh-agent-prompt" :direction="1" />
      </div>
    </Transition>
    <AgentStoryboard :steps="steps" :label="t('agentSetup.stepsLabel')" />
    <p class="agent-setup-hint">{{ t(state === 'guest' ? 'agentSetup.dsh.guestHint' : 'agentSetup.dsh.hint') }}</p>
    <template v-if="state === 'ready'">
      <McpConnectionStatus class="agent-setup-status" :connection="connection" variant="dsh" />
      <button type="button" class="agent-setup-link" @click="rotate">{{ t('dsh.wizard.tokenRotate') }}</button>
    </template>
    <p class="dsh-quota-hint">{{ t('dsh.wizard.memberStatus') }}</p>
  </section>
</template>
