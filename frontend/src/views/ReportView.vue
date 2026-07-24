<script setup lang="ts">
import { nextTick, onMounted, onUnmounted, ref, watch, computed } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import MarkdownIt from 'markdown-it'
import { api } from '../services/api'
import { useEventSource } from '../composables/useEventSource'
import { useReportSubscriptions } from '../composables/useReportSubscriptions'
import { useAuthStore } from '../stores/authStore'
import { Pin, Mail, BellRing, BellOff, Send } from 'lucide-vue-next'
import {
  DAILY_ONLY_TYPES,
  PERIOD_TYPES,
  REPORT_TYPES,
  coercePeriodForReport,
  coerceReportStreamText,
  getPeriodTypeInfo,
  getReportTypeInfo,
  isPeriodDisabled as isReportPeriodDisabled,
  type BatchSubscriptionResponse,
  type PeriodKey,
  type ReportKey,
  type ReportMessageResponse,
  type ReportResponse,
  type ReportStreamEvent,
  type SubscriptionListResponse,
} from '../features/report/reportViewModel'

const authStore = useAuthStore()
const router = useRouter()
const route = useRoute()

const md = new MarkdownIt({ html: false, linkify: true, breaks: true })

const reportContent = ref('')
const isGenerating = ref(false)
const isCached = ref(false)
const errorMsg = ref('')
const reportRef = ref<HTMLElement | null>(null)

const selectedType   = ref<ReportKey>('all')
const selectedPeriod = ref<PeriodKey>('daily')
const selectedDate   = ref<string>(new Date().toISOString().slice(0, 10))

const isPeriodDisabled = (periodKey: PeriodKey): boolean =>
  isReportPeriodDisabled(selectedType.value, periodKey)

const currentTypeInfo = computed(() => getReportTypeInfo(selectedType.value))
const currentPeriodInfo = computed(() => getPeriodTypeInfo(selectedPeriod.value))

// ── 订阅状态 ──────────────────────────────────────────────────────────

const {
  isSubscribing,
  isSendingEmail,
  emailSentMsg,
  showSubscribePanel,
  showLoginPrompt,
  selectedSubscribeSources,
  isSourceSubscribed,
  isCurrentSubscribed,
  promptLoginForSubscribe,
  closeLoginPrompt,
  handleLoginAndRedirect,
  handleManageSubscriptions,
  closeSubscribePanel,
  toggleSubscribeSource,
  confirmSubscribeSources,
  loadSubscriptions,
  toggleSubscribe,
  sendToEmail,
} = useReportSubscriptions({
  isLoggedIn: computed(() => authStore.isLoggedIn),
  selectedSource: selectedType,
  selectedPeriod,
  selectedDate,
  operations: {
    loadSubscriptions: async () => {
      const res = await api.get<SubscriptionListResponse>('/report/subscriptions')
      return res.data
    },
    subscribeSources: async payload => {
      const res = await api.post<BatchSubscriptionResponse>('/report/subscriptions/batch', payload)
      return res.data
    },
    unsubscribe: async payload => {
      await api.post('/report/unsubscribe', payload)
    },
    sendToEmail: async payload => {
      const res = await api.post<ReportMessageResponse>('/report/send-to-email', payload)
      return res.data
    },
  },
  redirectToLogin: () => {
    router.push({ path: '/login', query: { redirect: route.fullPath } })
  },
  setError: message => { errorMsg.value = message },
})

// ── 自动滚动 ──────────────────────────────────────────────────────────
const autoScroll = ref(true)
const onWheelHandler = (e: WheelEvent) => { if (e.deltaY < 0) autoScroll.value = false }
let lastTouchY = 0
const onTouchStart = (e: TouchEvent) => { lastTouchY = e.touches[0]?.clientY ?? 0 }
const onTouchMoveHandler = (e: TouchEvent) => {
  const currentY = e.touches[0]?.clientY ?? 0
  if (currentY > lastTouchY) autoScroll.value = false
  lastTouchY = currentY
}

const scrollToBottom = async () => {
  if (!autoScroll.value) return
  await nextTick()
  const el = reportRef.value
  if (!el) return
  el.scrollTop = el.scrollHeight
}

onMounted(() => {
  const el = reportRef.value
  if (el) {
    el.addEventListener('wheel', onWheelHandler, { passive: true })
    el.addEventListener('touchstart', onTouchStart, { passive: true })
    el.addEventListener('touchmove', onTouchMoveHandler, { passive: true })
  }
})

onUnmounted(() => {
  const el = reportRef.value
  if (el) {
    el.removeEventListener('wheel', onWheelHandler)
    el.removeEventListener('touchstart', onTouchStart)
    el.removeEventListener('touchmove', onTouchMoveHandler)
  }
})

// ── SSE 生成（仅 Admin） ──────────────────────────────────────────────
const generate = async () => {
  if (isGenerating.value) return
  isGenerating.value = true
  reportContent.value = ''
  errorMsg.value = ''
  autoScroll.value = true

  const { connect } = useEventSource()
  const baseURL = (api.defaults.baseURL ?? '').replace(/\/+$/, '')
  await connect({
    url: `${baseURL}/report/daily/stream`,
    body: {
      source: selectedType.value,
      date: selectedDate.value,
      period: selectedPeriod.value,
      force_regenerate: true,
    },
    onMessage: async (payload: unknown) => {
      const event = payload as ReportStreamEvent
      if (event.type === 'content' || event.type === 'chunk') {
        reportContent.value += coerceReportStreamText(event.data)
        await scrollToBottom()
      } else if (event.type === 'error') {
        errorMsg.value = String(event.data ?? 'Unknown error')
      }
    },
    onDone: () => { isGenerating.value = false },
    onError: (err: unknown) => { errorMsg.value = String(err); isGenerating.value = false },
  })
}

// ── 加载缓存 ──────────────────────────────────────────────────────────
const loadCachedReport = async () => {
  try {
    const res = await api.get<ReportResponse>('/report/latest', {
      params: { source: selectedType.value, period: selectedPeriod.value, date: selectedDate.value },
    })
    if (res.data?.content) { reportContent.value = res.data.content; isCached.value = true; errorMsg.value = ''; return }
    reportContent.value = ''; isCached.value = false
  } catch { reportContent.value = ''; isCached.value = false }
}

onMounted(() => {
  loadCachedReport()
  loadSubscriptions()
})

watch(selectedType, (type) => {
  selectedPeriod.value = coercePeriodForReport(type, selectedPeriod.value)
})

watch([selectedType, selectedPeriod, selectedDate], () => {
  if (isGenerating.value) return
  void loadCachedReport()
})
</script>

<template>
  <div class="report-shell flex h-full flex-col overflow-hidden p-4 gap-2.5">

    <!-- ═══ 紧凑型操作面板：标题 + 源选择 + 周期 + 操作按钮 ═══ -->
    <div class="stagger-enter glass-card shrink-0 px-4 py-3 space-y-2">
      <!-- 第一行：标题 + 状态 + 操作按钮 -->
      <div class="flex flex-wrap items-center justify-between gap-3">
        <div class="flex items-center gap-2 min-w-0">
          <component v-if="currentTypeInfo?.icon" :is="currentTypeInfo.icon" class="h-5 w-5 text-stone-500 shrink-0" />
          <h1 class="text-lg font-bold text-stone-800 tracking-tight font-serif truncate">{{ currentTypeInfo?.label || '自动化简报' }}</h1>
          <span class="text-xs text-stone-400 hidden sm:inline">{{ selectedDate }} · {{ currentPeriodInfo?.label }} · {{ currentTypeInfo?.desc }}</span>
        </div>
        <div class="flex w-full flex-wrap items-center gap-2 sm:w-auto sm:shrink-0">
          <div v-if="isCached && !isGenerating" class="flex items-center gap-1 rounded-full bg-green-50 px-2.5 py-1 border border-green-200">
            <span class="status-dot bg-brand-green" />
            <span class="text-2xs font-medium text-green-700">已缓存</span>
          </div>
          <div v-if="isGenerating" class="stream-indicator">
            <span class="stream-dot" />
            <span>生成中</span>
          </div>

          <!-- 订阅/取消订阅按钮 -->
          <button
            class="flex items-center gap-1 rounded-full px-2.5 py-1 text-2xs font-medium transition-all duration-200"
            :class="isCurrentSubscribed
              ? 'bg-amber-50 text-amber-700 border border-amber-200 hover:bg-amber-100'
              : 'bg-indigo-50 text-indigo-700 border border-indigo-200 hover:bg-indigo-100'"
            :disabled="isSubscribing"
            @click="authStore.isLoggedIn ? toggleSubscribe() : promptLoginForSubscribe()"
          >
            <span v-if="isSubscribing" class="h-3 w-3 rounded-full border-2 border-current/40 border-t-current animate-spin" />
            <BellOff v-else-if="isCurrentSubscribed" class="h-3 w-3" />
            <BellRing v-else class="h-3 w-3" />
            {{ isCurrentSubscribed ? '取消订阅' : '订阅' }}
          </button>

          <!-- 发送到邮箱 -->
          <button
            v-if="authStore.isLoggedIn && isCached && reportContent"
            class="flex items-center gap-1 rounded-full px-2.5 py-1 text-2xs font-medium bg-stone-50 text-stone-600 border border-stone-200 hover:bg-stone-100 transition-all duration-200"
            :disabled="isSendingEmail"
            @click="sendToEmail"
          >
            <span v-if="isSendingEmail" class="h-3 w-3 rounded-full border-2 border-stone-400/40 border-t-stone-500 animate-spin" />
            <Send v-else class="h-3 w-3" />
            发送简报
          </button>

          <!-- 操作成功提示 -->
          <span v-if="emailSentMsg" class="inline-flex items-center gap-1 rounded-full border border-green-200 bg-green-50 px-2.5 py-1 text-2xs font-medium text-green-700">
            <Mail class="h-3 w-3" />
            {{ emailSentMsg }}
          </span>

          <button
            v-if="authStore.isLoggedIn"
            class="flex items-center gap-1 rounded-full px-2.5 py-1 text-2xs font-medium bg-stone-50 text-stone-600 border border-stone-200 hover:bg-stone-100 transition-all duration-200"
            :disabled="isSubscribing"
            @click="handleManageSubscriptions"
          >
            <BellRing class="h-3 w-3" />
            管理订阅
          </button>

          <!-- Admin: 生成相关控件 -->
          <template v-if="authStore.isAdmin">
            <span v-if="isGenerating" class="flex items-center gap-1 text-2xs" :class="autoScroll ? 'text-cyan-600' : 'text-stone-400'">
              <span class="status-dot" :class="autoScroll ? 'bg-cyan-500 animate-[pulseDot_2s_ease-in-out_infinite]' : 'bg-stone-400'" />
              {{ autoScroll ? '跟随' : '解锁' }}
            </span>
            <button class="btn-primary gap-1.5 text-xs py-1.5 px-3" :disabled="isGenerating" @click="generate">
              <span v-if="isGenerating" class="h-3 w-3 rounded-full border-2 border-white/40 border-t-white animate-spin" />
              <svg v-else class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"/></svg>
              {{ isGenerating ? '生成中…' : isCached ? '重新生成' : '生成' }}
            </button>
          </template>
        </div>
      </div>

      <!-- 第二行：源选择 + 周期选择 -->
      <div class="flex flex-wrap items-center gap-2" style="border-top: 1px solid rgba(168,162,158,0.10); padding-top: 8px">
        <div class="flex max-w-full flex-nowrap gap-1.5 overflow-x-auto pb-1 sm:flex-wrap sm:overflow-visible">
          <button
            v-for="type in REPORT_TYPES"
            :key="type.key"
            class="flex shrink-0 items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium transition-all duration-200"
            :class="selectedType === type.key
              ? 'tab-active shadow-sm'
              : 'tab-inactive'"
            :style="selectedType !== type.key ? 'background: rgba(255,255,255,0.6); border: 1px solid rgba(168,162,158,0.20)' : ''"
            :disabled="isGenerating"
            @click="selectedType = type.key"
          >
            <component :is="type.icon" class="h-3 w-3 shrink-0" />
            <span>{{ type.label }}</span>
          </button>
        </div>

        <span class="text-stone-200">|</span>

        <div class="flex items-center gap-1">
          <button
            v-for="p in PERIOD_TYPES"
            :key="p.key"
            class="rounded-full px-3 py-1 text-xs font-medium transition-all duration-200"
            :class="[
              isPeriodDisabled(p.key) ? 'cursor-not-allowed opacity-30 text-stone-400'
                : selectedPeriod === p.key ? 'bg-cyan-50 text-cyan-700 font-semibold border border-cyan-200'
                : 'text-stone-400 hover:bg-accent-soft hover:text-stone-600'
            ]"
            :disabled="isGenerating || isPeriodDisabled(p.key)"
            @click="!isPeriodDisabled(p.key) && (selectedPeriod = p.key)"
          >{{ p.label }}</button>
          <span v-if="DAILY_ONLY_TYPES.has(selectedType)" class="flex items-center gap-0.5 text-2xs text-stone-400 ml-0.5">
            <Pin class="h-2.5 w-2.5 shrink-0" />
            仅日报
          </span>
        </div>

        <!-- Admin: 日期选择 -->
        <div v-if="authStore.isAdmin" class="flex items-center gap-1 ml-2">
          <input v-model="selectedDate" type="date" class="input w-auto py-1 text-xs" :disabled="isGenerating" />
        </div>
      </div>

      <!-- 游客订阅登录提示 -->
      <div v-if="showLoginPrompt" class="rounded-2xl border border-amber-100 bg-amber-50/90 p-3 shadow-sm">
        <div class="flex flex-wrap items-center justify-between gap-3">
          <div class="flex items-center gap-2 text-sm text-amber-800">
            <BellRing class="h-4 w-4 shrink-0" />
            <span>请先登录后再订阅简报，即将跳转到登录页面。</span>
          </div>
          <div class="flex items-center gap-2">
            <button class="rounded-full px-3 py-1.5 text-xs font-medium text-amber-700 hover:bg-amber-100" @click="closeLoginPrompt">稍后</button>
            <button class="rounded-full bg-amber-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-amber-700" @click="handleLoginAndRedirect">去登录</button>
          </div>
        </div>
      </div>

      <!-- 日报订阅领域选择 -->
      <div v-if="showSubscribePanel" class="rounded-2xl border border-indigo-100 bg-white/90 p-3 shadow-sm">
        <div class="flex items-start justify-between gap-3">
          <div>
            <p class="text-sm font-semibold text-stone-700">选择要订阅的日报领域</p>
            <p class="text-2xs text-stone-400 mt-0.5">日报生成后会自动推送到你的注册邮箱；综合简报与单领域报告会分别推送。</p>
          </div>
          <button class="text-2xs text-stone-400 hover:text-stone-600" :disabled="isSubscribing" @click="closeSubscribePanel">取消</button>
        </div>

        <div class="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          <button
            v-for="type in REPORT_TYPES"
            :key="type.key"
            type="button"
            class="flex items-center gap-2 rounded-xl border px-3 py-2 text-left transition-all duration-200"
            :class="selectedSubscribeSources.includes(type.key)
              ? 'border-indigo-200 bg-indigo-50 text-indigo-800'
              : 'border-stone-100 bg-white/70 text-stone-600 hover:bg-accent-soft'"
            :disabled="isSubscribing"
            @click="toggleSubscribeSource(type.key)"
          >
            <span class="flex h-4 w-4 items-center justify-center rounded border text-[10px]"
              :class="selectedSubscribeSources.includes(type.key) ? 'border-indigo-500 bg-indigo-500 text-white' : 'border-stone-300 text-transparent'">✓</span>
            <component :is="type.icon" class="h-4 w-4 shrink-0" />
            <span class="min-w-0 flex-1">
              <span class="block text-xs font-semibold">{{ type.label }}</span>
              <span class="block text-2xs opacity-70">{{ type.desc }}{{ isSourceSubscribed(type.key) ? ' · 已订阅' : '' }}</span>
            </span>
          </button>
        </div>

        <div class="mt-3 flex items-center justify-end gap-2">
          <button
            class="rounded-full px-3 py-1.5 text-xs font-medium text-stone-500 hover:bg-accent-soft"
            :disabled="isSubscribing"
            @click="closeSubscribePanel"
          >取消</button>
          <button
            class="btn-primary gap-1.5 text-xs py-1.5 px-3"
            :disabled="isSubscribing || !selectedSubscribeSources.length"
            @click="confirmSubscribeSources"
          >
            <span v-if="isSubscribing" class="h-3 w-3 rounded-full border-2 border-white/40 border-t-white animate-spin" />
            确定订阅 {{ selectedSubscribeSources.length }} 个领域
          </button>
        </div>
      </div>
    </div>

    <!-- 错误 -->
    <div v-if="errorMsg" class="shrink-0 glass-card flex items-center gap-2 px-4 py-2 text-xs text-rose-600">
      <svg class="h-3.5 w-3.5 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
      {{ errorMsg }}
    </div>

    <!-- ═══ 内容阅读区（最大化空间） ═══ -->
    <div ref="reportRef" class="stagger-enter glass-card relative flex-1 min-h-0 overflow-y-auto scroll-smooth" style="animation-delay: 0.1s">
      <!-- 空状态 -->
      <div v-if="!reportContent && !isGenerating" class="flex h-full flex-col items-center justify-center gap-2 text-stone-400 p-4">
        <div class="flex h-12 w-12 items-center justify-center rounded-2xl bg-stone-100">
          <svg class="h-6 w-6 opacity-30" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/></svg>
        </div>
        <p class="text-sm font-medium text-stone-500 font-serif">选择类型查看简报</p>
        <p class="text-xs text-center max-w-sm text-stone-400">综合 · 学术 · 工程 · 行业 · 产品 · 社区 | 日报 / 周报 / 月报</p>
      </div>

      <!-- 生成中骨架 -->
      <div v-if="isGenerating && !reportContent" class="p-5">
        <div class="flex items-center gap-2 text-sm text-stone-500 mb-3">
          <span class="status-dot bg-cyan-500 animate-[pulseDot_2s_ease-in-out_infinite]" />
          正在生成「{{ currentTypeInfo?.label }}」…
        </div>
        <div class="space-y-2.5 animate-pulse">
          <div class="h-5 w-48 rounded-lg bg-stone-100" />
          <div class="h-3.5 w-full rounded bg-stone-50" />
          <div class="h-3.5 w-5/6 rounded bg-stone-50" />
          <div class="h-3.5 w-4/6 rounded bg-stone-50" />
          <div class="h-5 w-36 rounded-lg bg-stone-100 mt-3" />
          <div class="h-3.5 w-full rounded bg-stone-50" />
          <div class="h-3.5 w-3/4 rounded bg-stone-50" />
        </div>
      </div>

      <!-- 报告正文 -->
      <div v-if="reportContent" class="p-5">
        <article class="prose-content prose-report max-w-none" v-html="md.render(reportContent)" />
        <span v-if="isGenerating" class="inline-block h-4 w-0.5 animate-pulse bg-cyan-500 align-middle ml-0.5" />
      </div>

      <!-- 回到底部按钮 -->
      <button
        v-if="isGenerating && !autoScroll"
        class="sticky bottom-4 ml-auto mr-4 btn-primary text-xs"
        @click="() => { autoScroll = true; scrollToBottom() }"
      >
        <svg class="h-3 w-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/></svg>
        回到底部
      </button>
    </div>
  </div>
</template>

<style scoped>
.report-shell {
  --paper: #f4f0e6;
  --paper-raised: #fffdf6;
  --ink: #191a16;
  --rule: rgba(25, 26, 22, 0.76);
  --lime: #c7ff2e;
  --lime-soft: #f1f9d2;
  background: var(--paper);
  color: var(--ink);
}

.report-shell :deep(.glass-card) {
  border: 1px solid var(--rule);
  border-radius: 6px;
  background: var(--paper-raised);
  box-shadow: 3px 3px 0 rgba(25, 26, 22, 0.1);
  backdrop-filter: none;
}

.report-shell button,
.report-shell input { border-radius: 4px; }

.report-shell button:focus-visible,
.report-shell input:focus-visible {
  outline: 2px solid var(--ink);
  outline-offset: 2px;
  box-shadow: 0 0 0 4px var(--lime);
}

.report-shell :deep(.btn-primary) {
  border: 1px solid var(--ink);
  border-radius: 4px;
  background: var(--ink);
  color: #fffdf6;
  box-shadow: none;
}

.report-shell :deep(.btn-primary:hover:not(:disabled)) {
  background: var(--lime);
  color: var(--ink);
}

.report-shell :deep(.tab-active) {
  border-color: var(--ink);
  background: var(--lime);
  color: var(--ink);
  box-shadow: inset 0 -3px 0 var(--ink);
}

.report-shell :deep(.tab-inactive:hover) {
  border-color: var(--ink);
  background: var(--lime-soft);
  color: var(--ink);
}

.report-shell button[class*="bg-indigo"],
.report-shell button[class*="border-indigo"],
.report-shell button[class*="bg-cyan"] {
  border-color: var(--ink) !important;
  background: var(--lime) !important;
  color: var(--ink) !important;
}

.report-shell [class*="text-cyan"],
.report-shell [class*="text-indigo"] { color: #4b6100 !important; }
.report-shell [class*="bg-cyan"] { background-color: var(--lime) !important; }

.report-shell > div:first-child > div:nth-child(2) {
  border-top-color: rgba(25, 26, 22, 0.24) !important;
}

.report-shell input[type="date"] {
  border-color: rgba(25, 26, 22, 0.45);
  background: var(--paper-raised);
}
</style>
