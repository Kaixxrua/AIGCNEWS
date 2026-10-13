<script setup lang="ts">
import { computed, onBeforeUnmount, ref, useId } from 'vue'
import { useI18n } from 'vue-i18n'
import { Bot, Check, ChevronDown, ClipboardCopy, Copy, MousePointerClick } from 'lucide-vue-next'
import { useAuthStore } from '@/stores/authStore'
import { useLoginPrompt } from '@/composables/useLoginPrompt'
import { useMcpAgentSetup } from '@/composables/useMcpAgentSetup'
import { showToast } from '@/composables/useToast'
import { MCP_MEMBER_QUOTA } from '@/features/mcp/dshPlugin'
import { installAgentSetupMessages } from '@/i18n/locales/agentSetup'
import { fold, unfold } from '@/motion/fold'
import RollText from '@/motion/RollText.vue'
import AgentStoryboard from './AgentStoryboard.vue'
import CommandPreview from './CommandPreview.vue'
import McpConnectionStatus from './McpConnectionStatus.vue'
import './agent-setup.css'

/**
 * /mcp 的主卡：一颗「复制给 Agent 的配置提示词」，选客户端、跑命令都交给用户自己的 Agent。
 * 提示词不带 Token（客户端走浏览器授权），游客也能复制、也能展开看全文；登录了附一枚一次性安装码（预览里是占位），
 * 也才看得到接入回显（要读自己的令牌列表），接上后在回显里报档位与额度。
 */
installAgentSetupMessages()

const { t, locale } = useI18n()
const auth = useAuthStore()
const { requestLogin } = useLoginPrompt()
const signedIn = computed(() => auth.isLoggedIn)
const setup = useMcpAgentSetup({
  signedIn,
  locale: () => locale.value,
  manualPageUrl: () => `${window.location.origin}/mcp`,
  copyNotice: { onError: () => showToast(t('mcp.copyFailed')) },
})
const { prompt, installCodeAvailable, installCodeReady, copiedKey, connection, copyPrompt } = setup
const installCodeSlot = { empty: 'agentSetup.installCode.slot', filled: 'agentSetup.installCode.slotFilled' }

const copied = computed(() => copiedKey.value === 'agent-prompt')
const previewOpen = ref(false)
const previewId = `agent-prompt-${useId()}`

const steps = computed(() => [
  { id: 'copy', icon: ClipboardCopy, title: t('agentSetup.mcp.steps.copy.title'), body: t('agentSetup.mcp.steps.copy.body') },
  { id: 'paste', icon: Bot, title: t('agentSetup.mcp.steps.paste.title'), body: t('agentSetup.mcp.steps.paste.body') },
  { id: 'allow', icon: MousePointerClick, title: t('agentSetup.mcp.steps.allow.title'), body: t('agentSetup.mcp.steps.allow.body') },
])

const count = (value: number) => value.toLocaleString(locale.value)
const tier = computed(() => {
  const quota = MCP_MEMBER_QUOTA
  const values = { daily: count(quota.rolling24h), monthly: count(quota.rolling30d) }
  return t('agentSetup.mcp.tier.member', values)
})

onBeforeUnmount(setup.dispose)
</script>

<template>
  <section class="agent-setup agent-setup--mcp mcp-hero" :aria-label="t('agentSetup.copyPrompt')">
    <p class="agent-setup-kicker">{{ t('agentSetup.mcp.kicker') }}</p>
    <p class="agent-setup-lede">{{ t('agentSetup.mcp.lede') }}</p>
    <div class="agent-setup-actions">
      <div class="agent-setup-face" aria-live="polite">
        <button type="button" class="agent-setup-cta" :class="{ 'agent-setup-cta--copied': copied }" @click="copyPrompt">
          <component :is="copied ? Check : Copy" class="agent-setup-cta-icon" aria-hidden="true" />
          <RollText :value="t(copied ? 'agentSetup.copied' : 'agentSetup.copyPrompt')" />
        </button>
      </div>
      <button type="button" class="agent-setup-toggle" :aria-expanded="previewOpen" :aria-controls="previewId" @click="previewOpen = !previewOpen">
        <ChevronDown class="agent-setup-toggle-icon" aria-hidden="true" />{{ t(previewOpen ? 'agentSetup.previewHide' : 'agentSetup.previewShow') }}
      </button>
    </div>
    <Transition @enter="unfold" @leave="fold">
      <div v-show="previewOpen" :id="previewId" role="region" :aria-label="t('agentSetup.previewLabel')">
        <CommandPreview class="agent-setup-preview" :command="prompt" :filled="installCodeReady" :slot-keys="installCodeSlot" swap-key="mcp-agent-prompt" :direction="1" />
      </div>
    </Transition>
    <AgentStoryboard :steps="steps" :label="t('agentSetup.stepsLabel')" />
    <p v-if="signedIn" class="agent-setup-hint">{{ t(installCodeAvailable ? 'agentSetup.mcp.hint' : 'agentSetup.mcp.hintNoCode') }}</p>
    <p v-else class="agent-setup-hint">
      {{ t('agentSetup.mcp.guestHint') }}
      <button type="button" class="agent-setup-link" @click="requestLogin('/mcp')">{{ t('agentSetup.loginForStatus') }}</button>
    </p>
    <McpConnectionStatus v-if="signedIn" class="agent-setup-status" :connection="connection" variant="agent">
      <template v-if="connection.status.value === 'connected'" #default>
        <p class="agent-setup-tier">{{ tier }}</p>
      </template>
    </McpConnectionStatus>
  </section>
</template>
