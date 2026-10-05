<script setup lang="ts">
import { computed, ref, useId, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { Check } from 'lucide-vue-next'
import type { TokenConnectionWatch } from '@/composables/useTokenConnectionWatch'
import { formatUsedAgo, parseTimestampMs } from '@/features/mcp/tokenConnectionModel'
import { installMcpConnectionMessages } from '@/i18n/locales/mcpConnection'
import { fold, unfold } from '@/motion/fold'
import { vMorph } from '@/motion/morph'
import { vSwap } from '@/motion/swap'
import RollText from '@/motion/RollText.vue'

/**
 * 接入命令旁的连接状态：令牌交给用户后显示「等待 X 连接… → 已连接」，等久了（或停止自动检测后）自动展开排障提示。
 * 状态由控制器里的 useTokenConnectionWatch 维护（只在页面可见时轮询），这里只管显示。
 * /mcp（client）与 /dsh（dsh）共用；外层已是 aria-live 区域时传 live=false，免得读屏读两遍。
 */
installMcpConnectionMessages()

const props = withDefaults(defineProps<{
  connection: TokenConnectionWatch
  variant?: 'client' | 'dsh'
  /** 客户端显示名（variant=client 时用）。 */
  client?: string
  live?: boolean
  /** 顶上一条虚线，与上方的复制按钮隔开；单独成块时关掉。 */
  divider?: boolean
}>(), { variant: 'client', client: '', live: true, divider: true })

const { t, locale } = useI18n()
const { status, lastUsedAt, fresh, slow, checking, checkNow } = props.connection
const tipsId = `token-connection-tips-${useId()}`

// 以前连过的 dsh 令牌单独一种样子（seen）：不是这次亲眼看到连上，不播「连上」的盖章。
const face = computed(() => (status.value === 'connected' && !fresh.value ? 'seen' : status.value))
const clientName = computed(() => (props.variant === 'dsh' ? 'dsh' : props.client))
const lastUsedMs = computed(() => parseTimestampMs(lastUsedAt.value))

const timeOfDay = (ms: number | null) => (
  ms == null
    ? t('mcpConnection.justNow')
    : new Intl.DateTimeFormat(locale.value, { hour: '2-digit', minute: '2-digit' }).format(ms)
)
const usedAgo = (ms: number | null) => (
  ms == null ? t('mcpConnection.justNow') : formatUsedAgo(ms, Date.now(), locale.value, t('mcpConnection.justNow'))
)

const title = computed(() => {
  switch (face.value) {
    case 'waiting': return t('mcpConnection.waitingTitle', { client: clientName.value })
    case 'connected': return t('mcpConnection.connectedTitle')
    case 'seen': return t('mcpConnection.seenTitle')
    case 'paused': return t('mcpConnection.pausedTitle')
    case 'gone': return t('mcpConnection.goneTitle')
    default: return ''
  }
})

const body = computed(() => {
  const dsh = props.variant === 'dsh'
  switch (face.value) {
    case 'waiting': return dsh ? t('mcpConnection.waitingBodyDsh') : t('mcpConnection.waitingBody', { client: clientName.value })
    case 'connected': return t('mcpConnection.connectedBody', { client: clientName.value, time: timeOfDay(lastUsedMs.value) })
    case 'seen': return t('mcpConnection.seenBody', { time: usedAgo(lastUsedMs.value) })
    case 'paused': return t('mcpConnection.pausedBody')
    case 'gone': return dsh ? t('mcpConnection.goneBodyDsh') : t('mcpConnection.goneBody')
    default: return ''
  }
})

// 按最常见的原因排：没重启、没提问（dsh 插件第一次搜索才连）、命令没跑完、用的不是最新那条。
const tips = computed(() => (props.variant === 'dsh'
  ? [
      t('mcpConnection.tips.dshRestart'),
      t('mcpConnection.tips.dshAsk'),
      t('mcpConnection.tips.dshConfig'),
      t('mcpConnection.tips.dshRotated', { rotate: t('dsh.wizard.tokenRotate') }),
    ]
  : [
      t('mcpConnection.tips.restart'),
      t('mcpConnection.tips.shell'),
      t('mcpConnection.tips.latest'),
      t('mcpConnection.tips.network', { verify: t('mcp.wizard.stepVerify') }),
    ]))

const canRetry = computed(() => face.value === 'waiting' || face.value === 'paused' || face.value === 'seen')
const tipsOpen = ref(false)
let tipsTouched = false
const tipsShown = computed(() => tipsOpen.value && canRetry.value)
const toggleTips = () => {
  tipsTouched = true
  tipsOpen.value = !tipsOpen.value
}
// 等久了或停止自动检测：替用户把排障提示打开；用户自己收起过就不再打扰。
watch(
  () => slow.value || status.value === 'paused',
  (stuck) => { if (stuck && !tipsTouched) tipsOpen.value = true },
  { immediate: true },
)
</script>

<template>
  <div v-if="face !== 'idle'" v-morph="face" class="token-connection" :class="[`token-connection--${face}`, { 'token-connection--divided': divider }]" :data-connection="face">
    <span class="token-connection-dot" aria-hidden="true"><Check v-if="face === 'connected' || face === 'seen'" class="token-connection-check" /></span>
    <div v-swap="{ key: face, y: 6 }" class="token-connection-text" :role="live ? 'status' : undefined">
      <p class="token-connection-title">{{ title }}</p>
      <p class="token-connection-body">{{ body }}</p>
    </div>
    <div v-if="canRetry" class="token-connection-actions">
      <button type="button" class="token-connection-link" data-connection-action="check" :disabled="checking" @click="checkNow"><RollText :value="t(checking ? 'mcpConnection.checking' : 'mcpConnection.checkAgain')" /></button>
      <button type="button" class="token-connection-link" data-connection-action="tips" :aria-expanded="tipsShown" :aria-controls="tipsId" @click="toggleTips">{{ t('mcpConnection.tipsToggle') }}</button>
    </div>
    <Transition @enter="unfold" @leave="fold">
      <ol v-show="tipsShown" :id="tipsId" class="token-connection-tips">
        <li v-for="tip in tips" :key="tip">{{ tip }}</li>
      </ol>
    </Transition>
  </div>
</template>

<style scoped>
.token-connection {
  display: grid;
  grid-template-columns: 18px minmax(0, 1fr);
  align-items: start;
  gap: 6px 10px;
  min-width: 0;
  color: var(--ink);
  font-size: 12.5px;
  line-height: 19px;
  text-align: left;
}

.token-connection--divided {
  padding-top: 10px;
  border-top: 1.5px dashed color-mix(in srgb, var(--rule-strong) 45%, transparent);
}

.token-connection-dot {
  position: relative;
  display: grid;
  place-items: center;
  justify-self: center;
  width: 14px;
  height: 14px;
  margin-top: 3px;
  border: 2px solid var(--rule-strong);
  border-radius: 50%;
  background: var(--paper-raised);
  color: var(--acid-ink);
}

/* 等待中：圆点外一圈墨线一下一下往外扩，像在发信号。 */
.token-connection--waiting .token-connection-dot::after {
  content: '';
  position: absolute;
  inset: -2px;
  border: 2px solid var(--rule-strong);
  border-radius: 50%;
  opacity: 0;
  animation: token-connection-ping 1.8s cubic-bezier(.22, 1, .36, 1) infinite;
}

.token-connection--paused .token-connection-dot { border-style: dashed; }

.token-connection--connected .token-connection-dot,
.token-connection--seen .token-connection-dot {
  width: 18px;
  height: 18px;
  margin-top: 1px;
  background: var(--acid);
}

.token-connection--seen .token-connection-dot { background: var(--acid-soft); color: var(--ink); }

/* 这次亲眼看到连上：圆点盖章式弹一下。 */
.token-connection--connected .token-connection-dot { animation: token-connection-stamp 520ms cubic-bezier(.34, 1.56, .64, 1); }

.token-connection--gone .token-connection-dot { border-color: var(--danger); background: var(--danger); }

.token-connection-check { width: 12px; height: 12px; stroke-width: 3.5; }

.token-connection-text { min-width: 0; }

.token-connection-title { margin: 0; font-size: 13.5px; font-weight: 900; line-height: 20px; }

.token-connection-body { margin: 2px 0 0; }

.token-connection-actions,
.token-connection-tips { grid-column: 2; }

.token-connection-actions { display: flex; flex-wrap: wrap; gap: 4px 16px; }

.token-connection-link {
  padding: 0;
  border: 0;
  background: none;
  color: var(--ink);
  font: inherit;
  font-weight: 800;
  text-decoration: underline;
  text-decoration-thickness: 1.5px;
  text-underline-offset: 3px;
  cursor: pointer;
}

.token-connection-link:disabled { cursor: default; opacity: .6; }
.token-connection-link:focus-visible { outline: 2px solid var(--ink); outline-offset: 2px; border-radius: 2px; }

.token-connection-tips {
  display: grid;
  gap: 4px;
  margin: 0;
  padding: 0 0 0 18px;
  list-style: decimal;
}

@keyframes token-connection-ping {
  0% { opacity: .6; transform: scale(1); }
  100% { opacity: 0; transform: scale(2.1); }
}

@keyframes token-connection-stamp {
  0% { transform: scale(.4); }
  100% { transform: scale(1); }
}

@media (prefers-reduced-motion: reduce) {
  .token-connection--waiting .token-connection-dot::after { animation: none; opacity: .35; transform: scale(1.5); }
  .token-connection--connected .token-connection-dot { animation: none; }
}
</style>
