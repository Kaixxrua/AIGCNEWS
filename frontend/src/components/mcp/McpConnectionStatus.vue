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
 * 接入回显：交出提示词或令牌后显示「等待… → 已接入」，等久了（或停止自动检测后）自动展开排障提示。
 * 状态由 useTokenConnectionWatch 维护（只在页面可见时轮询），这里只管显示。三种用法：
 * - agent：/mcp「复制给 Agent」之后等新授权的客户端（startNew），中间多一步「已授权，等它连上」；
 * - manual：/mcp 手动配置签发的令牌；dsh：/dsh 的专用令牌，以前连过的显示上次使用时间。
 * 默认插槽拿到当前 face，排在说明文字下面（例如接入后的档位与额度）。外层已是 aria-live 区域时传 live=false，免得读屏读两遍。
 */
installMcpConnectionMessages()

/** OAuth 客户端注册时没报名字，后端（routes_mcp_oauth._FALLBACK_CLIENT_LABEL）记成这个。 */
const UNNAMED_OAUTH_CLIENT = 'MCP OAuth'
const CLIENT_NAME_MAX = 40

const props = withDefaults(defineProps<{
  connection: TokenConnectionWatch
  variant?: 'agent' | 'manual' | 'dsh'
  live?: boolean
  /** 顶上一条虚线，与上方的复制按钮隔开；单独成块时关掉。 */
  divider?: boolean
}>(), { variant: 'agent', live: true, divider: true })

const { t, locale } = useI18n()
const { status, lastUsedAt, fresh, slow, checking, clientLabel, checkNow } = props.connection
const tipsId = `token-connection-tips-${useId()}`

// 以前连过的 dsh 令牌单独一种样子（seen）：不是这次亲眼看到连上，不播「连上」的盖章。
const face = computed(() => (status.value === 'connected' && !fresh.value ? 'seen' : status.value))
const lastUsedMs = computed(() => parseTimestampMs(lastUsedAt.value))
// 客户端名是 OAuth 注册时它自己报的（授权页上提示过未经核实），只拿来显示，太长的截断。
const agentClient = computed(() => {
  const label = clientLabel.value?.trim()
  if (!label || label === UNNAMED_OAUTH_CLIENT) return ''
  return label.length > CLIENT_NAME_MAX ? `${label.slice(0, CLIENT_NAME_MAX - 1)}…` : label
})

const timeOfDay = (ms: number | null) => (
  ms == null
    ? t('mcpConnection.justNow')
    : new Intl.DateTimeFormat(locale.value, { hour: '2-digit', minute: '2-digit' }).format(ms)
)
const usedAgo = (ms: number | null) => (
  ms == null ? t('mcpConnection.justNow') : formatUsedAgo(ms, Date.now(), locale.value, t('mcpConnection.justNow'))
)

const agentText = (part: 'title' | 'body') => {
  const client = agentClient.value
  const time = timeOfDay(lastUsedMs.value)
  switch (face.value) {
    case 'waiting': return t(part === 'title' ? 'mcpConnection.agent.waitingTitle' : 'mcpConnection.agent.waitingBody')
    case 'authorized':
      if (part === 'body') return t('mcpConnection.agent.authorizedBody')
      return client ? t('mcpConnection.agent.authorizedTitle', { client }) : t('mcpConnection.agent.authorizedTitleUnnamed')
    case 'connected':
      if (part === 'title') return t('mcpConnection.agent.connectedTitle')
      return client ? t('mcpConnection.agent.connectedBody', { client, time }) : t('mcpConnection.agent.connectedBodyUnnamed', { time })
    case 'paused': return t(part === 'title' ? 'mcpConnection.agent.pausedTitle' : 'mcpConnection.agent.pausedBody')
    default: return ''
  }
}

const tokenText = (part: 'title' | 'body') => {
  const dsh = props.variant === 'dsh'
  const title = part === 'title'
  switch (face.value) {
    case 'waiting':
      if (title) return dsh ? t('mcpConnection.waitingTitle', { client: 'dsh' }) : t('mcpConnection.manual.waitingTitle')
      return dsh ? t('mcpConnection.waitingBodyDsh') : t('mcpConnection.manual.waitingBody')
    case 'connected': {
      const time = timeOfDay(lastUsedMs.value)
      if (title) return t('mcpConnection.connectedTitle')
      return dsh ? t('mcpConnection.connectedBody', { client: 'dsh', time }) : t('mcpConnection.manual.connectedBody', { time })
    }
    case 'seen': return title ? t('mcpConnection.seenTitle') : t('mcpConnection.seenBody', { time: usedAgo(lastUsedMs.value) })
    case 'paused': return t(title ? 'mcpConnection.pausedTitle' : 'mcpConnection.pausedBody')
    case 'gone': return title ? t('mcpConnection.goneTitle') : t(dsh ? 'mcpConnection.goneBodyDsh' : 'mcpConnection.goneBody')
    default: return ''
  }
}

const title = computed(() => (props.variant === 'agent' ? agentText('title') : tokenText('title')))
const body = computed(() => (props.variant === 'agent' ? agentText('body') : tokenText('body')))

// 按最常见的原因排。Agent：授权页没打开、授权用错账号、没重启；dsh：没重启、没提问（插件第一次搜索才连）；
// 手动配置：没重启、配置没合并好、用的不是最新那份。
const tips = computed(() => {
  switch (props.variant) {
    case 'agent': return [
      t('mcpConnection.tips.agentBrowser'),
      t('mcpConnection.tips.agentAccount'),
      t('mcpConnection.tips.restart'),
      t('mcpConnection.tips.agentNetwork'),
    ]
    case 'dsh': return [
      t('mcpConnection.tips.dshRestart'),
      t('mcpConnection.tips.dshAsk'),
      t('mcpConnection.tips.dshConfig'),
      t('mcpConnection.tips.dshRotated', { rotate: t('dsh.wizard.tokenRotate') }),
    ]
    default: return [
      t('mcpConnection.tips.restart'),
      t('mcpConnection.tips.manualConfig'),
      t('mcpConnection.tips.latest'),
      t('mcpConnection.tips.network'),
    ]
  }
})

const canRetry = computed(() => ['waiting', 'authorized', 'paused', 'seen'].includes(face.value))
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
    <div v-if="$slots.default" class="token-connection-extra"><slot :face="face" /></div>
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

/* 已授权、等客户端连上：半填的圆点，外圈接着往外扩。 */
.token-connection--authorized .token-connection-dot { background: var(--acid-soft); }

.token-connection--authorized .token-connection-dot::after {
  content: '';
  position: absolute;
  inset: -2px;
  border: 2px solid var(--rule-strong);
  border-radius: 50%;
  opacity: 0;
  animation: token-connection-ping 1.8s cubic-bezier(.22, 1, .36, 1) infinite;
}

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

.token-connection-extra,
.token-connection-actions,
.token-connection-tips { grid-column: 2; }

.token-connection-extra { min-width: 0; }

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
  .token-connection--waiting .token-connection-dot::after,
  .token-connection--authorized .token-connection-dot::after { animation: none; opacity: .35; transform: scale(1.5); }
  .token-connection--connected .token-connection-dot { animation: none; }
}
</style>
