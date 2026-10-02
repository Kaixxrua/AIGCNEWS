<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useElementSize, useMediaQuery } from '@vueuse/core'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import type { BroadsheetSaves, ReportReadingMode } from '@/components/report/ReportBroadsheet.vue'
import ReportContentPanel from '@/components/report/ReportContentPanel.vue'
import ReportControlsPanel from '@/components/report/ReportControlsPanel.vue'
import ReportSavedPanel from '@/components/report/ReportSavedPanel.vue'
import ReportSubscriptionPanel from '@/components/report/ReportSubscriptionPanel.vue'
import { api } from '@/services/http/apiClient'
import { getFeedToken, rotateFeedToken } from '@/services/auth/feedTokenApi'
import { useEventSource } from '@/composables/useEventSource'
import { useFollowViewport } from '@/composables/useFollowViewport'
import { useReportBarLayout } from '@/composables/useReportBarLayout'
import { useReportController } from '@/composables/useReportController'
import { useReportSubscriptions } from '@/composables/useReportSubscriptions'
import { useLatexRenderer } from '@/composables/useLatexRenderer'
import { useSavedItems } from '@/composables/useSavedItems'
import { useAuthStore } from '@/stores/authStore'
import { useLoginPrompt } from '@/composables/useLoginPrompt'
import { vSwap } from '@/motion/swap'
import { briefingSaveId, isSavedBriefingItem } from '@/features/saved/savedBriefing'
import {
  getReportTypeInfo,
  parseReportDateQuery,
  parseReportTypeQuery,
  type ReportKey,
  type ReportResponse,
  type SubscriptionListResponse,
  type SubscriptionPlan,
  type SubscriptionPlanApplyResponse,
} from '@/features/report/reportViewModel'

const { locale, t } = useI18n()
const authStore = useAuthStore()
const { requestLogin } = useLoginPrompt()
const route = useRoute()
const router = useRouter()

// 从 Dashboard 一键订阅入口进入时，自动打开订阅向导；已登录则清理 query 避免重复触发。
onMounted(() => {
  if (route.query.subscribe === '1') {
    toggleSubscribe()
    if (authStore.isLoggedIn) {
      void router.replace({ query: { ...route.query, subscribe: undefined } })
    }
  }
})

const { renderMarkdown } = useLatexRenderer()
const reportRef = ref<HTMLElement | null>(null)
const reportPageRef = ref<HTMLElement | null>(null)
const isMobile = useMediaQuery('(max-width: 767px)')
// 桌面（≥1024px）按大报版式排，整页只留一条滚动条，跟随生成滚动的也是整页。
const isDesktop = useMediaQuery('(min-width: 1024px)')
const readingViewport = computed(() => isMobile.value || isDesktop.value ? reportPageRef.value : reportRef.value)
// 控制条钉在顶部时有多高：收起长条目后把条目开头滚回控制条下方要让开这段距离。
const controlsRef = ref<HTMLElement | null>(null)
const { height: controlsHeight } = useElementSize(controlsRef, undefined, { box: 'border-box' })
// 桌面控制条三段（分区标签、日期行、操作按钮）放得下就排一行，否则按宽度排成两行。
const controlsLayout = useReportBarLayout(controlsRef, isDesktop)
const { autoScroll, resetAutoScroll, scrollToBottom, resumeAutoScroll } = useFollowViewport(readingViewport)

const { connect } = useEventSource()
const {
  reportContent,
  isGenerating,
  isCached,
  errorMsg,
  selectedSource: selectedType,
  selectedDate,
  generate,
} = useReportController({
  operations: {
    loadCachedReport: async (params, signal) => {
      const res = await api.get<ReportResponse>('/report/latest', { params, signal })
      return res.data
    },
    connectReportStream: ({ source, date, locale: reportLocale, onMessage, onDone, onError }) => {
      const baseURL = (api.defaults.baseURL ?? '').replace(/\/+$/, '')
      return connect({
        url: `${baseURL}/report/daily/stream`,
        body: { source, date, locale: reportLocale, force_regenerate: true },
        onMessage,
        onDone,
        onError,
      })
    },
  },
  resetAutoScroll,
  scrollToBottom,
  locale,
  initialDate: parseReportDateQuery(route.query.date),
  initialSource: parseReportTypeQuery(route.query.type),
})

// RSS 简报条目按期号回链（?date=）：页内改选日期后同步地址栏，刷新或分享不回跳旧一期。
watch(selectedDate, date => {
  if (typeof route.query.date === 'string' && route.query.date !== date) {
    void router.replace({ query: { ...route.query, date } })
  }
})
// 站内速查的简报结果连种类一起回链（?type=）：页内改选种类同样同步地址栏。
watch(selectedType, type => {
  if (typeof route.query.type === 'string' && route.query.type !== type) {
    void router.replace({ query: { ...route.query, type } })
  }
})

const currentTypeInfo = computed(() => getReportTypeInfo(selectedType.value))

// ── 订阅状态 ──────────────────────────────────────────────────────────

const {
  isSubscribing,
  isSendingEmail,
  emailSentMsg,
  showSubscribePanel,
  showLoginPrompt,
  step,
  selectedSources,
  selectedDeliveryKeys,
  isLoadingPlan,
  isRssBusy,
  rssNotice,
  rssSubscribed,
  emailSubscribed,
  copySubscribedRss,
  canSelectMultipleSources,
  hasExistingPlan,
  deliveryCapabilities,
  promptLoginForSubscribe,
  closeLoginPrompt,
  handleLoginAndRedirect,
  closeSubscribePanel,
  toggleSubscribeSource,
  goToDeliveryStep,
  goBackToSourceStep,
  toggleDelivery,
  confirmSubscriptionPlan,
  copyRssLink,
  rotateRssToken,
  toggleSubscribe,
  sendToEmail,
} = useReportSubscriptions({
  isLoggedIn: computed(() => authStore.isLoggedIn),
  userId: computed(() => authStore.user?.user_id ?? null),
  selectedSource: selectedType,
  selectedDate,
  locale,
  operations: {
    loadPlan: async () => {
      const res = await api.get<SubscriptionPlan>('/report/subscription-plan')
      return res.data
    },
    loadSubscriptions: async () => {
      const res = await api.get<SubscriptionListResponse>('/report/subscriptions')
      return res.data
    },
    applyPlan: async payload => {
      const res = await api.post<SubscriptionPlanApplyResponse>('/report/subscription-plan', payload)
      return res.data
    },
    getFeedToken,
    rotateFeedToken,
    sendToEmail: async payload => {
      const res = await api.post<{ message: string }>('/report/send-to-email', payload)
      return res.data
    },
  },
  redirectToLogin: () => {
    requestLogin(route.fullPath)
  },
  setError: message => { errorMsg.value = message },
})

const userEmail = computed(() => authStore.user?.email ?? '')

// 换了简报类型/日期后读到的新内容整块浮现；生成时的流式追加不算换内容。
// 版面上是哪一期跟着内容换：改选之后、新一期读到之前，版面上还是上一期。
const contentKey = ref(0)
const shownIssue = ref({ type: selectedType.value, date: selectedDate.value })
watch(reportContent, () => {
  if (!isGenerating.value) contentKey.value += 1
  shownIssue.value = { type: selectedType.value, date: selectedDate.value }
})

// 本机收藏（只在桌面大报版）：条目底行的书签或按 s 收下，连同哪一期一起存在本机；分区标签最后多一枚「收藏」，
// 切过去把收下的条目按期排成一份大报。换分区、改日期就回到简报。
const savedBriefing = useSavedItems({ list: 'briefing', accept: isSavedBriefingItem })
const briefingSaves: BroadsheetSaves = {
  has: item => savedBriefing.has(briefingSaveId(shownIssue.value.type, shownIssue.value.date, item)),
  toggle: (item, place) => {
    const { type, date } = shownIssue.value
    savedBriefing.toggle(briefingSaveId(type, date, item), { type, date, ...place, item })
  },
}
const savedView = ref(false)
watch(savedView, () => {
  contentKey.value += 1
  readingViewport.value?.scrollTo({ top: 0 })
})
watch(isDesktop, desktop => { if (!desktop) savedView.value = false })
const pickType = (type: ReportKey) => {
  selectedType.value = type
  savedView.value = false
}
const pickDate = (date: string) => {
  selectedDate.value = date
  savedView.value = false
}
// 已经在简报页时，站内速查跳来另一期（同一页只换了 ?date= / ?type=）：跟着换过去。页面被缓存着时不跟别的页的参数走。
watch(() => [route.name, route.query.date, route.query.type], ([name, date, type]) => {
  if (name !== 'report') return
  const nextDate = parseReportDateQuery(date)
  const nextType = parseReportTypeQuery(type)
  if (nextDate && nextDate !== selectedDate.value) pickDate(nextDate)
  if (nextType && nextType !== selectedType.value) pickType(nextType)
})

// 大报版式的阅读方式（全文 / 导读）记在本机，下次打开沿用；无痕窗口等存不了时只在本次有效。
const READING_MODE_KEY = 'report_reading_mode'
const readStoredReadingMode = (): ReportReadingMode => {
  try {
    return localStorage.getItem(READING_MODE_KEY) === 'lead' ? 'lead' : 'full'
  } catch {
    return 'full'
  }
}
const readingMode = ref<ReportReadingMode>(readStoredReadingMode())
watch(readingMode, mode => {
  try {
    localStorage.setItem(READING_MODE_KEY, mode)
  } catch {
    // 存不了就不存
  }
})
</script>

<template>
  <div ref="reportPageRef" class="report-shell flex h-full flex-col overflow-hidden p-4 gap-2.5" :style="{ '--report-bar-h': `${Math.round(controlsHeight)}px` }">

    <!-- ═══ 紧凑型操作面板：标题 + 源选择 + 周期 + 操作按钮 ═══ -->
    <div ref="controlsRef" class="stagger-enter glass-card comic-panel shrink-0 px-4 py-3 space-y-2" :class="[{ 'is-expanded': showSubscribePanel || showLoginPrompt }, controlsLayout && `is-${controlsLayout}`]">
      <ReportControlsPanel
        :selected-type="selectedType"
        :selected-date="selectedDate"
        :current-type-info="currentTypeInfo"
        :is-cached="isCached"
        :is-generating="isGenerating"
        :is-logged-in="authStore.isLoggedIn"
        :is-admin="authStore.isAdmin"
        :is-subscribing="isSubscribing"
        :is-sending-email="isSendingEmail"
        :email-sent-msg="emailSentMsg"
        :rss-subscribed="rssSubscribed"
        :email-subscribed="emailSubscribed"
        :user-email="userEmail"
        :is-rss-busy="isRssBusy"
        :report-content="reportContent"
        :auto-scroll="autoScroll"
        :reading-mode="isDesktop ? readingMode : null"
        :saved-count="isDesktop ? savedBriefing.count.value : null"
        :saved-view="savedView"
        @update:selected-type="pickType"
        @update:selected-date="pickDate"
        @update:reading-mode="readingMode = $event"
        @update:saved-view="savedView = $event"
        @toggle-subscribe="toggleSubscribe"
        @prompt-login-for-subscribe="promptLoginForSubscribe"
        @send-to-email="sendToEmail"
        @copy-subscribed-rss="copySubscribedRss"
        @generate="generate"
      />

      <ReportSubscriptionPanel
        :show-login-prompt="showLoginPrompt"
        :show-subscribe-panel="showSubscribePanel"
        :is-subscribing="isSubscribing"
        :is-loading-plan="isLoadingPlan"
        :is-rss-busy="isRssBusy"
        :rss-notice="rssNotice"
        :user-email="userEmail"
        :step="step"
        :selected-sources="selectedSources"
        :selected-delivery-keys="selectedDeliveryKeys"
        :delivery-capabilities="deliveryCapabilities"
        :can-select-multiple-sources="canSelectMultipleSources"
        :has-existing-plan="hasExistingPlan"
        @close-login-prompt="closeLoginPrompt"
        @login-and-redirect="handleLoginAndRedirect"
        @close-subscribe-panel="closeSubscribePanel"
        @toggle-subscribe-source="toggleSubscribeSource"
        @go-next="goToDeliveryStep"
        @go-back="goBackToSourceStep"
        @toggle-delivery="toggleDelivery"
        @copy-rss="copyRssLink"
        @rotate-rss="rotateRssToken"
        @confirm-plan="confirmSubscriptionPlan"
      />
      <!-- 桌面版控制条贴在报眉下，正文滚过时由这条墨线隔开 -->
      <svg v-if="isDesktop" class="report-controls__rule" viewBox="0 0 1000 6" preserveAspectRatio="none" aria-hidden="true"><path d="M0 3.4 L340 2.6 L1000 3.8" /></svg>
    </div>

    <!-- 错误 -->
    <div v-if="errorMsg" class="shrink-0 glass-card flex items-center gap-2 px-4 py-2 text-xs text-rose-600">
      <svg class="h-3.5 w-3.5 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
      {{ errorMsg }}
    </div>

    <!-- ═══ 内容阅读区（最大化空间） ═══ -->
    <div ref="reportRef" v-swap="{ key: contentKey, stagger: true }" class="report-reading stagger-enter glass-card relative flex-1 min-h-0 overflow-y-auto scroll-smooth" style="animation-delay: 0.1s">
      <ReportSavedPanel v-if="savedView" :mode="readingMode" />
      <ReportContentPanel
        v-else
        :report-content="reportContent"
        :is-generating="isGenerating"
        :current-type-label="currentTypeInfo ? t(`report.type.${currentTypeInfo.labelKey}`) : ''"
        :auto-scroll="autoScroll"
        :render-markdown="renderMarkdown"
        :reading-mode="isDesktop ? readingMode : null"
        :content-key="contentKey"
        :saves="isDesktop ? briefingSaves : null"
        @resume-auto-scroll="resumeAutoScroll"
      />
    </div>
  </div>
</template>

<style scoped>
.report-shell {
  --paper: var(--chat-paper);
  --paper-raised: var(--paper-warm);
  --ink: var(--chat-ink);
  background: var(--paper);
  color: var(--ink);
}

@media (max-width: 767px) {
  .report-shell { display: block; overflow-y: auto; padding: 16px; }
  .report-reading { min-height: 320px; margin-top: 16px; overflow: visible; }
  .report-shell :deep(button), .report-shell :deep(input) { min-height: 44px; }
  .report-shell :deep(.report-content) { padding: 16px; }
}

/* 控制条下的墨线只在漫画版桌面布局里画（comic-pages.css） */
.report-controls__rule { display: none; }

.report-shell :deep(.glass-card) {
  border: 1px solid var(--rule);
  border-radius: var(--module-radius);
  background: var(--paper-raised);
  box-shadow: none;
  backdrop-filter: none;
}

.report-shell :deep(button),
.report-shell :deep(input) { border-radius: var(--control-radius); }

.report-shell :deep(button:focus-visible),
.report-shell :deep(input:focus-visible) {
  outline: 2px solid var(--ink);
  outline-offset: 2px;
  box-shadow: 0 0 0 3px var(--acid-soft);
}

.report-shell :deep(.btn-primary) {
  border: 1px solid var(--ink);
  border-radius: var(--control-radius);
  background: var(--ink);
  color: var(--paper-raised);
  box-shadow: none;
}

.report-shell :deep(.btn-primary:hover:not(:disabled)) {
  background: var(--acid-bright);
  color: var(--chat-on-acid);
}

.report-shell :deep(.tab-active) {
  border-color: var(--ink);
  background: var(--acid-bright);
  color: var(--chat-on-acid);
  box-shadow: none;
}

.report-shell :deep(.tab-inactive:hover) {
  border-color: var(--ink);
  background: var(--acid-mist);
  color: var(--ink);
}

.report-shell :deep(button[class*="bg-indigo"]),
.report-shell :deep(button[class*="border-indigo"]),
.report-shell :deep(button[class*="bg-cyan"]) {
  border-color: var(--ink) !important;
  background: var(--acid-bright) !important;
  color: var(--chat-on-acid) !important;
}

.report-shell :deep([class*="text-cyan"]),
.report-shell :deep([class*="text-indigo"]) { color: var(--on-acid) !important; }
.report-shell :deep([class*="bg-cyan"]) { background-color: var(--acid-bright) !important; }

.report-shell :deep(.space-y-2 > div:nth-child(2)) {
  border-top-color: rgb(var(--chat-ink-rgb) / 0.24) !important;
}

.report-shell :deep(input[type="date"]) {
  border-color: rgb(var(--chat-ink-rgb) / 0.45);
  background: var(--paper-raised);
}

/* 移动端：外壳与操作卡收窄边距，把宽度让给内容阅读区 */
@media (max-width: 639px) {
  .report-shell > .glass-card:first-child { padding: 12px; }
}
</style>
