<script setup lang="ts">
import { computed, onBeforeUnmount } from 'vue'
import { useI18n } from 'vue-i18n'
import { Check, Copy, Link2 } from 'lucide-vue-next'
import { copyToClipboard } from '@/composables/useClipboard'
import { useCopyNotice } from '@/composables/useCopyNotice'
import { showToast } from '@/composables/useToast'
import { MCP_OAUTH_ENDPOINT } from '@/features/mcp/mcpOAuth'
import { installAgentSetupMessages } from '@/i18n/locales/agentSetup'
import RollText from '@/motion/RollText.vue'
import './agent-setup.css'

/**
 * /mcp 侧栏的第一条备用路径：只能粘一个远程 MCP 地址的客户端，填这一行；连接时客户端自己打开浏览器授权。
 * 地址不带 Token，游客也能复制。
 */
installAgentSetupMessages()

const { t } = useI18n()
const notice = useCopyNotice({ onError: () => showToast(t('mcp.copyFailed')) })
const copied = computed(() => notice.copiedKey.value === 'endpoint')

const copyEndpoint = () => notice.copy('endpoint', () => copyToClipboard(MCP_OAUTH_ENDPOINT))
// 卡片窄到放不下一行时，从最后一个斜杠后折开（…/mcp/ 与 oauth），不在单词中间断。
const endpointBreak = MCP_OAUTH_ENDPOINT.lastIndexOf('/') + 1
const endpointHead = MCP_OAUTH_ENDPOINT.slice(0, endpointBreak)
const endpointTail = MCP_OAUTH_ENDPOINT.slice(endpointBreak)

onBeforeUnmount(notice.dispose)
</script>

<template>
  <section class="agent-card agent-endpoint-card">
    <h2 class="agent-card-title"><Link2 class="agent-card-icon" aria-hidden="true" />{{ t('agentSetup.mcp.endpoint.title') }}</h2>
    <p class="agent-card-text">{{ t('agentSetup.mcp.endpoint.body') }}</p>
    <p class="agent-endpoint" translate="no">{{ endpointHead }}<wbr>{{ endpointTail }}</p>
    <div class="agent-card-actions" aria-live="polite">
      <button type="button" class="agent-btn" @click="copyEndpoint">
        <component :is="copied ? Check : Copy" class="agent-btn-icon" aria-hidden="true" />
        <RollText :value="t(copied ? 'mcp.copied' : 'agentSetup.mcp.endpoint.copy')" />
      </button>
    </div>
  </section>
</template>
