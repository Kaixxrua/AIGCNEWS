<script setup lang="ts">
import { computed, onBeforeUnmount, ref, useId, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { Check, ChevronDown, Copy, Github, Package, SquareTerminal } from 'lucide-vue-next'
import { useAuthStore } from '@/stores/authStore'
import { useLoginPrompt } from '@/composables/useLoginPrompt'
import { copySensitiveToClipboard } from '@/composables/useClipboard'
import { useCopyNotice } from '@/composables/useCopyNotice'
import type { DshSetupController } from '@/composables/useDshSetupController'
import { showToast } from '@/composables/useToast'
import { COMMAND_TOKEN_SLOT } from '@/features/mcp/commandPreview'
import { DSH_PLUGIN_INSTALL_METHODS, buildDshInstallLine, type DshPluginInstallMethodId } from '@/features/mcp/dshPlugin'
import { installAgentSetupMessages } from '@/i18n/locales/agentSetup'
import { fold, unfold } from '@/motion/fold'
import { vIndicator } from '@/motion/indicator'
import { vSwap } from '@/motion/swap'
import RollText from '@/motion/RollText.vue'
import CommandPreview from '@/components/mcp/CommandPreview.vue'
import '@/components/mcp/agent-setup.css'

/**
 * /dsh 侧栏折叠起来的「手动安装」：不经过 Agent，选 npm 或 GitHub，复制一行命令自己在终端里跑。
 * 和主卡共用页面的控制器（同一枚 Token、同一个连接检测）；命令模板随时可看，Token 处是占位，
 * 带 Token 的命令只进安全剪贴板。Token 的取回、旧版 Token 的重新生成和出错重试都在主卡上。
 */
installAgentSetupMessages()

const props = defineProps<{ controller: DshSetupController }>()

const { t } = useI18n()
const auth = useAuthStore()
const { requestLogin } = useLoginPrompt()
const { selectedMethod, phase, token, command, installLine, connection } = props.controller
const notice = useCopyNotice({ onError: () => showToast(t('mcp.copyFailed')) })
const copied = computed(() => notice.copiedKey.value === 'dsh-install-line')

const open = ref(false)
const bodyId = `dsh-manual-${useId()}`
const methods = DSH_PLUGIN_INSTALL_METHODS
const method = computed(() => methods.find((item) => item.id === selectedMethod.value) ?? methods[0]!)

// 新命令沿切换方向滑入：切到右边的标签，从右边进来。
const direction = ref(1)
const methodIndex = (id: DshPluginInstallMethodId) => methods.findIndex((item) => item.id === id)
watch(selectedMethod, (next, previous) => { direction.value = methodIndex(next) < methodIndex(previous) ? -1 : 1 })
const pick = (id: DshPluginInstallMethodId) => { selectedMethod.value = id }

const ready = computed(() => auth.isLoggedIn && phase.value === 'ready' && !!token.value)
const preview = computed(() => buildDshInstallLine(command.value, COMMAND_TOKEN_SLOT))

const copyLine = async () => {
  if (!installLine.value) return
  if (await notice.copy('dsh-install-line', () => copySensitiveToClipboard(installLine.value))) connection.nudge()
}

onBeforeUnmount(notice.dispose)
</script>

<template>
  <section class="agent-card agent-manual dsh-manual" :class="{ 'agent-manual--open': open }">
    <h2 class="agent-card-title">
      <button type="button" class="agent-manual-toggle" :aria-expanded="open" :aria-controls="bodyId" @click="open = !open">
        <SquareTerminal class="agent-card-icon" aria-hidden="true" />
        <span>{{ t('agentSetup.dsh.manual.title') }}</span>
        <ChevronDown class="agent-manual-chevron" aria-hidden="true" />
      </button>
    </h2>
    <Transition @enter="unfold" @leave="fold">
      <div v-show="open" :id="bodyId" class="agent-manual-body">
        <p class="agent-card-text">{{ t('agentSetup.dsh.manual.summary') }}</p>
        <div v-indicator="{ active: '[aria-pressed=true]' }" class="agent-tabs" role="group" :aria-label="t('dsh.wizard.stepInstall')">
          <button
            v-for="item in methods"
            :key="item.id"
            type="button"
            class="agent-tab"
            :aria-pressed="selectedMethod === item.id"
            @click="pick(item.id)"
          >
            <component :is="item.id === 'npm' ? Package : Github" class="agent-tab-icon" aria-hidden="true" />{{ t(item.titleKey) }}<span v-if="item.recommended" class="agent-tab-tag">{{ t('dsh.recommended') }}</span>
          </button>
        </div>
        <p v-swap="{ key: selectedMethod, x: direction * 10, y: 0 }" class="agent-card-text agent-manual-method">{{ t(method.descriptionKey) }}</p>
        <CommandPreview class="agent-manual-command" :command="preview" :filled="ready" :swap-key="selectedMethod" :direction="direction" />
        <div class="agent-manual-face" aria-live="polite">
          <button v-if="!auth.isLoggedIn" type="button" class="agent-btn" @click="requestLogin('/dsh')">{{ t('mcp.desk.loginToCopy') }}</button>
          <button v-else type="button" class="agent-btn agent-btn--ink" :disabled="!ready" @click="copyLine">
            <component :is="copied ? Check : Copy" class="agent-btn-icon" aria-hidden="true" />
            <RollText :value="t(copied ? 'mcp.copied' : 'dsh.copy')" />
          </button>
        </div>
        <p class="agent-card-note">{{ t(ready ? 'dsh.wizard.tokenCommandNote' : 'mcp.desk.tokenNote') }}</p>
      </div>
    </Transition>
  </section>
</template>
