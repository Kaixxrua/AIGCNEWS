<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useMediaQuery } from '@vueuse/core'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import ReportContentPanel from '@/components/report/ReportContentPanel.vue'
import ReportControlsPanel from '@/components/report/ReportControlsPanel.vue'
import ReportSubscriptionPanel from '@/components/report/ReportSubscriptionPanel.vue'
import { api } from '@/services/http/apiClient'
import { getFeedToken, rotateFeedToken } from '@/services/auth/feedTokenApi'
import { useEventSource } from '@/composables/useEventSource'
import { useFollowViewport } from '@/composables/useFollowViewport'
import { useReportController } from '@/composables/useReportController'
import { useReportSubscriptions } from '@/composables/useReportSubscriptions'
import { useLatexRenderer } from '@/composables/useLatexRenderer'
import { useAuthStore } from '@/stores/authStore'
import { useLoginPrompt } from '@/composables/useLoginPrompt'
import {
  getReportTypeInfo,
  parseReportDateQuery,
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
const readingViewport = computed(() => isMobile.value ? reportPageRef.value : reportRef.value)
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
})

// RSS 简报条目按期号回链（?date=）：页内改选日期后同步地址栏，刷新或分享不回跳旧一期。
watch(selectedDate, date => {
  if (typeof route.query.date === 'string' && route.query.date !== date) {
    void router.replace({ query: { ...route.query, date } })
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
</script>

<template>
  <div ref="reportPageRef" class="report-shell flex h-full flex-col overflow-hidden p-4 gap-2.5">

    <!-- ═══ 紧凑型操作面板：标题 + 源选择 + 周期 + 操作按钮 ═══ -->
    <div class="stagger-enter glass-card shrink-0 px-4 py-3 space-y-2">
      <ReportControlsPanel
        v-model:selected-type="selectedType"
        v-model:selected-date="selectedDate"
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
    </div>

    <!-- 错误 -->
    <div v-if="errorMsg" class="shrink-0 glass-card flex items-center gap-2 px-4 py-2 text-xs text-rose-600">
      <svg class="h-3.5 w-3.5 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
      {{ errorMsg }}
    </div>

    <!-- ═══ 内容阅读区（最大化空间） ═══ -->
    <div ref="reportRef" class="report-reading stagger-enter glass-card relative flex-1 min-h-0 overflow-y-auto scroll-smooth" style="animation-delay: 0.1s">
      <ReportContentPanel
        :report-content="reportContent"
        :is-generating="isGenerating"
        :current-type-label="currentTypeInfo ? t(`report.type.${currentTypeInfo.labelKey}`) : ''"
        :auto-scroll="autoScroll"
        :render-markdown="renderMarkdown"
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
