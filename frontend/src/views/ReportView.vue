<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import ReportContentPanel from '../components/report/ReportContentPanel.vue'
import ReportControlsPanel from '../components/report/ReportControlsPanel.vue'
import ReportSubscriptionPanel from '../components/report/ReportSubscriptionPanel.vue'
import { api } from '../services/http/apiClient'
import { useEventSource } from '../composables/useEventSource'
import { useFollowViewport } from '../composables/useFollowViewport'
import { useReportController } from '../composables/useReportController'
import { useReportSubscriptions } from '../composables/useReportSubscriptions'
import { useLatexRenderer } from '../composables/useLatexRenderer'
import { useAuthStore } from '../stores/authStore'
import {
  getPeriodTypeInfo,
  getReportTypeInfo,
  isPeriodDisabled as isReportPeriodDisabled,
  type BatchSubscriptionResponse,
  type PeriodKey,
  type ReportMessageResponse,
  type ReportResponse,
  type SubscriptionListResponse,
} from '../features/report/reportViewModel'

const authStore = useAuthStore()
const router = useRouter()
const route = useRoute()

const { renderMarkdown } = useLatexRenderer()
const reportRef = ref<HTMLElement | null>(null)
const { autoScroll, resetAutoScroll, scrollToBottom, resumeAutoScroll } = useFollowViewport(reportRef)

const { connect } = useEventSource()
const {
  reportContent,
  isGenerating,
  isCached,
  errorMsg,
  selectedSource: selectedType,
  selectedPeriod,
  selectedDate,
  generate,
} = useReportController({
  operations: {
    loadCachedReport: async params => {
      const res = await api.get<ReportResponse>('/report/latest', { params })
      return res.data
    },
    connectReportStream: ({ source, date, period, onMessage, onDone, onError }) => {
      const baseURL = (api.defaults.baseURL ?? '').replace(/\/+$/, '')
      return connect({
        url: `${baseURL}/report/daily/stream`,
        body: { source, date, period, force_regenerate: true },
        onMessage,
        onDone,
        onError,
      })
    },
  },
  resetAutoScroll,
  scrollToBottom,
})

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
</script>

<template>
  <div class="report-shell flex h-full flex-col overflow-hidden p-4 gap-2.5">

    <!-- ═══ 紧凑型操作面板：标题 + 源选择 + 周期 + 操作按钮 ═══ -->
    <div class="stagger-enter glass-card shrink-0 px-4 py-3 space-y-2">
      <ReportControlsPanel
        v-model:selected-type="selectedType"
        v-model:selected-period="selectedPeriod"
        v-model:selected-date="selectedDate"
        :current-type-info="currentTypeInfo"
        :current-period-info="currentPeriodInfo"
        :is-cached="isCached"
        :is-generating="isGenerating"
        :is-logged-in="authStore.isLoggedIn"
        :is-admin="authStore.isAdmin"
        :is-current-subscribed="isCurrentSubscribed"
        :is-subscribing="isSubscribing"
        :is-sending-email="isSendingEmail"
        :email-sent-msg="emailSentMsg"
        :report-content="reportContent"
        :auto-scroll="autoScroll"
        :is-period-disabled="isPeriodDisabled"
        @toggle-subscribe="toggleSubscribe"
        @prompt-login-for-subscribe="promptLoginForSubscribe"
        @send-to-email="sendToEmail"
        @manage-subscriptions="handleManageSubscriptions"
        @generate="generate"
      />

      <ReportSubscriptionPanel
        :show-login-prompt="showLoginPrompt"
        :show-subscribe-panel="showSubscribePanel"
        :is-subscribing="isSubscribing"
        :selected-subscribe-sources="selectedSubscribeSources"
        :is-source-subscribed="isSourceSubscribed"
        @close-login-prompt="closeLoginPrompt"
        @login-and-redirect="handleLoginAndRedirect"
        @close-subscribe-panel="closeSubscribePanel"
        @toggle-subscribe-source="toggleSubscribeSource"
        @confirm-subscribe-sources="confirmSubscribeSources"
      />
    </div>

    <!-- 错误 -->
    <div v-if="errorMsg" class="shrink-0 glass-card flex items-center gap-2 px-4 py-2 text-xs text-rose-600">
      <svg class="h-3.5 w-3.5 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
      {{ errorMsg }}
    </div>

    <!-- ═══ 内容阅读区（最大化空间） ═══ -->
    <div ref="reportRef" class="stagger-enter glass-card relative flex-1 min-h-0 overflow-y-auto scroll-smooth" style="animation-delay: 0.1s">
      <ReportContentPanel
        :report-content="reportContent"
        :is-generating="isGenerating"
        :current-type-label="currentTypeInfo?.label"
        :auto-scroll="autoScroll"
        :render-markdown="renderMarkdown"
        @resume-auto-scroll="resumeAutoScroll"
      />
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

.report-shell :deep(button),
.report-shell :deep(input) { border-radius: 4px; }

.report-shell :deep(button:focus-visible),
.report-shell :deep(input:focus-visible) {
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

.report-shell :deep(button[class*="bg-indigo"]),
.report-shell :deep(button[class*="border-indigo"]),
.report-shell :deep(button[class*="bg-cyan"]) {
  border-color: var(--ink) !important;
  background: var(--lime) !important;
  color: var(--ink) !important;
}

.report-shell :deep([class*="text-cyan"]),
.report-shell :deep([class*="text-indigo"]) { color: #4b6100 !important; }
.report-shell :deep([class*="bg-cyan"]) { background-color: var(--lime) !important; }

.report-shell :deep(.space-y-2 > div:nth-child(2)) {
  border-top-color: rgba(25, 26, 22, 0.24) !important;
}

.report-shell :deep(input[type="date"]) {
  border-color: rgba(25, 26, 22, 0.45);
  background: var(--paper-raised);
}
</style>
