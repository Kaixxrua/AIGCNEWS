<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import type { McpConnectController } from '@/composables/useMcpConnectController'
import { mcpClientOptions, mcpShellOptions, type McpClientId, type McpShellId } from '@/features/mcp/mcpClientCatalog'
import { generateMcpClientCommand } from '@/features/mcp/mcpCommandGenerator'
import { COMMAND_TOKEN_SLOT } from '@/features/mcp/commandPreview'
import { resolveMcpFeedback } from '@/features/mcp/mcpFeedback'
import { clientConfigTarget, clientDescription, setupResultDescription, setupScopeLabel, setupTargetDescription } from '@/features/mcp/mcpSetupTarget'
import { installMcpOAuthSetupMessages } from '@/i18n/locales/mcpOAuthSetup'
import { vIndicator } from '@/motion/indicator'
import { vMorph } from '@/motion/morph'
import { vSwap } from '@/motion/swap'
import RollText from '@/motion/RollText.vue'
import CommandPreview from './CommandPreview.vue'
import McpConnectionStatus from './McpConnectionStatus.vue'

/**
 * /mcp 桌面版的接入命令台：不再分三步翻页。默认选中 Claude Code，命令与复制按钮打开就在首屏；九个客户端
 * 缩成一排标签，换标签命令跟着换。
 * 支持 MCP OAuth 的客户端默认给浏览器授权版：命令里没有 Token，游客也能直接复制，运行后在本站授权页登录、点「同意」，
 * 客户端自己拿到 Token。右栏底下的小链接可改用手动 Token：页面上只有命令模板，Token 处是占位，游客点复制先登录；
 * 登录后点「生成我的配置命令」才签发 Token（每点一次新建一枚，所以不在打开页面时自动签发），带 Token 的真实命令只进剪贴板。
 * 窄屏仍用三步向导（McpSetupWizard），两者共用视图里的同一个控制器。
 */
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
  oauthCommand,
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

// 新命令沿切换方向滑入：切到右边的标签，从右边进来。
const direction = ref(1)
const clientIndex = (id: McpClientId) => mcpClientOptions.findIndex((client) => client.id === id)
const shellIndex = (id: McpShellId) => mcpShellOptions.findIndex((shell) => shell.id === id)
watch(selectedClient, (next, previous) => { direction.value = clientIndex(next) < clientIndex(previous) ? -1 : 1 })
watch(selectedShell, (next, previous) => { direction.value = shellIndex(next) < shellIndex(previous) ? -1 : 1 })

// 浏览器授权版的命令没有密钥，原样摆出来；Token 版用占位串代替 Token 生成模板
const previewCommand = computed(() => (
  authMode.value === 'oauth'
    ? oauthCommand.value
    : generateMcpClientCommand(clientOption.value, normalizedEndpoint.value, COMMAND_TOKEN_SLOT, selectedShell.value)
))
const previewKey = computed(() => `${selectedClient.value}:${selectedShell.value}:${authMode.value}`)
const encodedLabel = computed(() => (authMode.value === 'oauth' ? t('mcpOAuthSetup.encodedSlot') : undefined))
const scopeLabel = computed(() => setupScopeLabel(clientOption.value, t, authMode.value))
const configTarget = computed(() => clientConfigTarget(clientOption.value, t))
const targetDescription = computed(() => setupTargetDescription(clientOption.value, selectedShell.value, t, authMode.value))
const resultDescription = computed(() => setupResultDescription(clientOption.value, t, authMode.value))
const setupErrorDisplay = computed(() => resolveMcpFeedback(setupError.value, t))
const testMessageDisplay = computed(() => resolveMcpFeedback(testMessage.value, t))
const endpointWarning = computed(() => (endpointWarningKey.value ? t(endpointWarningKey.value) : ''))

// 右栏：浏览器授权版直接复制；Token 版游客先登录，登录后签发 Token；签发中；命令就绪可复制；出错可重试。
const deskState = computed(() => {
  if (authMode.value === 'oauth') return 'oauth'
  if (!isLoggedIn.value) return 'guest'
  if (creating.value) return 'creating'
  if (transientCommand.value) return 'ready'
  return setupError.value ? 'error' : 'idle'
})
</script>

<template>
  <section class="mcp-desk" :aria-label="t('mcp.desk.ariaLabel')">
    <div class="mcp-desk-clients">
      <p class="mcp-desk-label"><span class="mcp-desk-num" aria-hidden="true">1</span>{{ t('mcp.desk.stepClient') }}</p>
      <div v-indicator="{ active: '[aria-pressed=true]' }" class="mcp-desk-tabs" role="group" :aria-label="t('mcp.desk.stepClient')">
        <button v-for="client in mcpClientOptions" :key="client.id" type="button" class="mcp-desk-tab" :aria-pressed="selectedClient === client.id" :title="clientDescription(client, t, authModeFor(client))" @click="selectedClient = client.id">{{ clientDisplayLabel(client) }}</button>
      </div>
    </div>

    <div class="mcp-desk-main">
      <div class="mcp-desk-head">
        <p class="mcp-desk-label"><span class="mcp-desk-num" aria-hidden="true">2</span>{{ t('mcp.wizard.stepCommand') }}</p>
        <div v-indicator="{ active: '[aria-pressed=true]' }" class="mcp-desk-tabs mcp-desk-tabs--shell" role="group" :aria-label="t('mcp.terminal')">
          <button v-for="shell in mcpShellOptions" :key="shell.id" type="button" class="mcp-desk-tab" :aria-pressed="selectedShell === shell.id" @click="selectedShell = shell.id">{{ shell.labelKey ? t(shell.labelKey) : shell.label }}</button>
        </div>
        <p v-swap="{ key: previewKey, x: direction * 10, y: 0 }" class="mcp-desk-target"><span class="mcp-desk-scope">{{ scopeLabel }}</span><span class="mcp-desk-path">{{ configTarget }}</span></p>
      </div>
      <CommandPreview :command="previewCommand" :filled="Boolean(transientCommand)" :swap-key="previewKey" :direction="direction" :encoded-label="encodedLabel" />
    </div>

    <div class="mcp-desk-side" :class="`mcp-desk-side--${deskState}`" aria-live="polite">
      <div v-morph="deskState" v-swap="{ key: deskState, y: 8 }" class="mcp-desk-side-body">
        <template v-if="deskState === 'oauth'">
          <p class="mcp-desk-side-title">{{ t('mcpOAuthSetup.title') }}</p>
          <button type="button" class="btn-primary" data-desk-action="copy-oauth" @click="copyGeneratedCommand"><RollText :value="t(copiedKey === 'command' ? 'mcp.copied' : 'mcpAutoCommand.copy')" /></button>
          <button type="button" class="btn-secondary" :title="t('mcpOAuthSetup.agentPromptHint')" @click="copyAgentSetupPrompt"><RollText :value="t(copiedKey === 'agent-prompt' ? 'mcp.copied' : 'mcpAutoCommand.copyAgentPrompt')" /></button>
          <p v-if="setupErrorDisplay" class="mcp-desk-error">{{ setupErrorDisplay }}</p>
          <p class="mcp-desk-note">{{ targetDescription }}</p>
          <p class="mcp-desk-note">{{ resultDescription }}</p>
          <button type="button" class="mcp-desk-switch" data-desk-action="use-token" @click="setAuthMode('token')">{{ t('mcpOAuthSetup.useToken') }}</button>
        </template>
        <template v-else-if="deskState === 'ready'">
          <p class="mcp-desk-side-title">{{ t('mcpAutoCommand.ready') }}</p>
          <button type="button" class="btn-primary" @click="copyGeneratedCommand"><RollText :value="t(copiedKey === 'command' ? 'mcp.copied' : 'mcpAutoCommand.copy')" /></button>
          <button type="button" class="btn-secondary" :title="t('mcpAutoCommand.agentPromptHint')" @click="copyAgentSetupPrompt"><RollText :value="t(copiedKey === 'agent-prompt' ? 'mcp.copied' : 'mcpAutoCommand.copyAgentPrompt')" /></button>
          <p v-if="setupErrorDisplay" class="mcp-desk-error">{{ setupErrorDisplay }}</p>
          <McpConnectionStatus :connection="connection" :client="clientDisplayLabel(clientOption)" :live="false" />
          <p class="mcp-desk-note mcp-desk-note--warn">{{ t('mcp.bearerWarningDetail') }}</p>
          <p class="mcp-desk-note">{{ resultDescription }}</p>
        </template>
        <template v-else-if="deskState === 'error'">
          <p class="mcp-desk-error">{{ setupErrorDisplay }}</p>
          <button type="button" class="btn-primary" @click="startSetup">{{ t('common.retry') }}</button>
        </template>
        <template v-else>
          <p class="mcp-desk-side-title">{{ targetDescription }}</p>
          <button v-if="deskState === 'guest'" type="button" class="btn-primary" @click="requestLogin">{{ t('mcp.desk.loginToCopy') }}</button>
          <button v-else type="button" class="btn-primary" data-desk-action="generate" :disabled="deskState === 'creating'" @click="startSetup"><RollText :value="t(deskState === 'creating' ? 'mcp.desk.creating' : 'mcp.desk.generate')" /></button>
          <p class="mcp-desk-note">{{ t(deskState === 'guest' ? 'mcp.desk.guestHint' : 'mcp.desk.generateHint') }}</p>
          <p class="mcp-desk-note">{{ t('mcp.desk.tokenNote') }}</p>
        </template>
        <button v-if="deskState !== 'oauth' && clientOption.oauth" type="button" class="mcp-desk-switch" data-desk-action="use-oauth" @click="setAuthMode('oauth')">{{ t('mcpOAuthSetup.useOAuth') }}</button>
      </div>
    </div>

    <div class="mcp-desk-verify">
      <p class="mcp-desk-label"><span class="mcp-desk-num" aria-hidden="true">3</span>{{ t('mcp.wizard.stepVerify') }}</p>
      <input v-model.trim="endpointUrl" class="input mcp-desk-endpoint" spellcheck="false" :aria-label="t('mcp.endpointAria')" />
      <button type="button" class="btn-secondary" :disabled="testing || Boolean(endpointWarning)" @click="testPublicHandshake"><RollText :value="t(testing ? 'mcp.testing' : 'mcp.publicHandshake')" /></button>
      <ol class="mcp-desk-phases">
        <li v-for="phase in testPhases" :key="phase.label" class="mcp-desk-phase" :data-status="phase.status"><span>{{ t(`mcp.phase.${phase.descriptionKey}`) }}</span><RollText :value="phase.detail ? resolveMcpFeedback(phase.detail, t) : t(`mcp.phaseStatus.${phase.status}`)" /></li>
      </ol>
      <p v-if="endpointWarning" class="mcp-desk-error">{{ endpointWarning }}</p>
      <p v-else-if="testMessageDisplay" class="mcp-desk-note">{{ testMessageDisplay }}</p>
    </div>
  </section>
</template>
