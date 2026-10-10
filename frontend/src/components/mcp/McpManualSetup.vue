<script setup lang="ts">
import { computed, onBeforeUnmount, ref, useId, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { Check, ChevronDown, Copy, Wrench } from 'lucide-vue-next'
import { useAuthStore } from '@/stores/authStore'
import { useLoginPrompt } from '@/composables/useLoginPrompt'
import { useMcpManualSetup } from '@/composables/useMcpManualSetup'
import { showToast } from '@/composables/useToast'
import { manualMcpEndpoint } from '@/features/mcp/manualMcpConfig'
import { installAgentSetupMessages } from '@/i18n/locales/agentSetup'
import { fold, unfold } from '@/motion/fold'
import { vMorph } from '@/motion/morph'
import { vSwap } from '@/motion/swap'
import RollText from '@/motion/RollText.vue'
import CommandPreview from './CommandPreview.vue'
import McpConnectionStatus from './McpConnectionStatus.vue'
import './agent-setup.css'

/**
 * /mcp 侧栏折叠起来的「手动配置」：给不支持浏览器授权的客户端，也用来排障。
 * 配置模板一展开就看得到（Token 处是占位）；登录后点「生成配置」才签 Token，带 Token 的配置只进安全剪贴板。
 * 登出或会话失效立即丢掉内存里的 Token。
 */
installAgentSetupMessages()

const { t } = useI18n()
const auth = useAuthStore()
const { requestLogin } = useLoginPrompt()
const manual = useMcpManualSetup({
  endpoint: () => manualMcpEndpoint(window.location.origin),
  copyNotice: { onError: () => showToast(t('mcp.copyFailed')) },
})
const { phase, error, preview, copiedKey, connection, generate, copyConfig, clear } = manual

const open = ref(false)
const bodyId = `manual-mcp-${useId()}`
const state = computed(() => (auth.isLoggedIn ? phase.value : 'guest'))
const copied = computed(() => copiedKey.value === 'manual-config')

watch(() => auth.status, (status) => { if (status !== 'authenticated') clear() })
onBeforeUnmount(manual.dispose)
</script>

<template>
  <section class="agent-card agent-manual" :class="{ 'agent-manual--open': open }">
    <h2 class="agent-card-title">
      <button type="button" class="agent-manual-toggle" :aria-expanded="open" :aria-controls="bodyId" @click="open = !open">
        <Wrench class="agent-card-icon" aria-hidden="true" />
        <span>{{ t('agentSetup.mcp.manual.title') }}</span>
        <ChevronDown class="agent-manual-chevron" aria-hidden="true" />
      </button>
    </h2>
    <Transition @enter="unfold" @leave="fold">
      <div v-show="open" :id="bodyId" class="agent-manual-body">
        <p class="agent-card-text">{{ t('agentSetup.mcp.manual.summary') }}</p>
        <CommandPreview class="agent-manual-config" :command="preview" :filled="state === 'ready'" swap-key="manual-config" :direction="1" />
        <div v-morph="state" class="agent-manual-actions" aria-live="polite">
          <div v-swap="{ key: state, y: 6 }" class="agent-manual-face">
            <button v-if="state === 'guest'" type="button" class="agent-btn" @click="requestLogin('/mcp')">{{ t('agentSetup.mcp.manual.login') }}</button>
            <button v-else-if="state === 'ready'" type="button" class="agent-btn agent-btn--ink" @click="copyConfig">
              <component :is="copied ? Check : Copy" class="agent-btn-icon" aria-hidden="true" />
              <RollText :value="t(copied ? 'mcp.copied' : 'agentSetup.mcp.manual.copy')" />
            </button>
            <button v-else-if="state === 'creating'" type="button" class="agent-btn" disabled>{{ t('agentSetup.mcp.manual.creating') }}</button>
            <template v-else-if="state === 'error'">
              <p class="agent-card-error">{{ t(error) }}</p>
              <button type="button" class="agent-btn" @click="generate">{{ t('agentSetup.mcp.manual.retry') }}</button>
            </template>
            <button v-else type="button" class="agent-btn" @click="generate">{{ t('agentSetup.mcp.manual.generate') }}</button>
          </div>
        </div>
        <McpConnectionStatus v-if="state === 'ready'" :connection="connection" variant="manual" />
        <p class="agent-card-note">{{ t('agentSetup.mcp.manual.note') }}</p>
      </div>
    </Transition>
  </section>
</template>
