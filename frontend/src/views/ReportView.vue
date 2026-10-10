<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useElementSize, useMediaQuery } from '@vueuse/core'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { isAxiosError } from 'axios'
import type { BroadsheetSaves, ReportReadingMode } from '@/components/report/ReportBroadsheet.vue'
import ReportContentPanel from '@/components/report/ReportContentPanel.vue'
import ReportControlsPanel from '@/components/report/ReportControlsPanel.vue'
import { reportPaperPeek, reportSavedPanel } from '@/components/report/desktopParts'
import ReportSubscriptionPanel from '@/components/report/ReportSubscriptionPanel.vue'
import { api } from '@/services/http/apiClient'
import { getFeedToken, rotateFeedToken } from '@/services/auth/feedTokenApi'
import { useEventSource } from '@/composables/useEventSource'
import { useFollowViewport } from '@/composables/useFollowViewport'
import { useReportBarLayout } from '@/composables/useReportBarLayout'
import { useReportController } from '@/composables/useReportController'
import { useReportPeek } from '@/composables/useReportPeek'
import { useReportSubscriptions } from '@/composables/useReportSubscriptions'
import { useLatexRenderer } from '@/composables/useLatexRenderer'
import { useSavedItems } from '@/composables/useSavedItems'
import { useAppDensity } from '@/composables/useAppDensity'
import { useAuthStore } from '@/stores/authStore'
import { useLoginPrompt } from '@/composables/useLoginPrompt'
import { slideIn, slideOut } from '@/motion/presence'
import { vSwap } from '@/motion/swap'
import { preloadWhen } from '@/utils/lazyComponent'
import { usePageHead } from '@/seo/pageHead'
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

// 某一期简报（RSS 与站内速查按 ?date= 回链）单独收录：标题带上日期，canonical 保留期号和种类。
// 不带期号的 /report 是「今天这一期」，用路由级的默认标题。
usePageHead(() => {
  const date = parseReportDateQuery(route.query.date)
  if (!date) return null
  const type = parseReportTypeQuery(route.query.type)
  return { title: `${t('seo.titles.report')} ${date}`, canonicalQuery: { date, type: type === 'all' ? null : type } }
})

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
// 报眉的版面密度选了舒适时，桌面也回到一节一张卡的长文；导读、条目收藏与宽屏论文栏都跟着大报版式走。
const { comfortable } = useAppDensity()
const broadsheetOn = computed(() => isDesktop.value && !comfortable.value)
// 控制条钉在顶部时有多高：收起长条目后把条目开头滚回控制条下方要让开这段距离。
const controlsRef = ref<HTMLElement | null>(null)
const { height: controlsHeight } = useElementSize(controlsRef, undefined, { box: 'border-box' })
// 桌面控制条三段（分区标签、日期行、操作按钮）放得下就排一行，否则按宽度排成两行。
const controlsLayout = useReportBarLayout(controlsRef, isDesktop)
// 宽屏的论文详情栏钉在控制条下、页脚卷角之上，栏高按整页可视高度算。
const isWide = useMediaQuery('(min-width: 1600px)')
const { height: pageHeight } = useElementSize(reportPageRef, undefined, { box: 'border-box' })
const { autoScroll, resetAutoScroll, scrollToBottom, resumeAutoScroll } = useFollowViewport(readingViewport)

const { connect } = useEventSource()
const {
  reportContent,
  isPreview,
  isGenerating,
  isCached,
  errorMsg,
  selectedSource: selectedType,
  selectedDate,
  loadState,
  issueDate,
  fallbackFrom,
  selectDate,
  retry: retryLoad,
  generate,
} = useReportController({
  operations: {
    // 那天没有这一期时接口回 404：交给控制器往前找或提示，不算读取失败
    loadCachedReport: async (params, signal) => {
      try {
        await authStore.ensureInitialized()
        const endpoint = authStore.isLoggedIn ? '/report/latest' : '/report/preview'
        const res = await api.get<ReportResponse>(endpoint, { params, signal })
        return res.data
      } catch (error) {
        if (isAxiosError(error) && error.response?.status === 404) return undefined
        throw error
      }
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
  isLoggedIn: computed(() => authStore.isLoggedIn),
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
const loginForFullReport = () => requestLogin(router.resolve({
  path: '/report', query: { ...route.query, date: selectedDate.value, type: selectedType.value }, hash: route.hash,
}).fullPath)

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
// 换内容或换版面（报眉的版面密度）时正文整块浮现
const readingKey = computed(() => `${contentKey.value}:${broadsheetOn.value ? 'sheet' : 'cards'}`)
const shownIssue = ref({ type: selectedType.value, date: selectedDate.value })
watch(reportContent, () => {
  if (!isGenerating.value) contentKey.value += 1
  shownIssue.value = { type: selectedType.value, date: selectedDate.value }
})

// 宽屏（≥1600px）点简报条目里的论文（讲到论文的条目的标题、论文链接）不离开简报：详情在右侧打开，列表留在左边，
// j / k 或栏里的上一条、下一条接着看。生成中不开；换一期、换分区、进出收藏时收起。
const peek = useReportPeek({ available: computed(() => isWide.value && broadsheetOn.value && !isGenerating.value) })
const {
  target: peekTarget,
  current: peekPaper,
  entry: peekEntry,
  entries: peekEntries,
  index: peekIndex,
  direction: peekDirection,
  withinItem: peekWithinItem,
} = peek
const broadsheetPeek = computed(() => (isWide.value && broadsheetOn.value ? peek.broadsheet : null))
// 详情栏单独成包（components/report/desktopParts.ts），手机不下载；到了宽屏大报版先取回来。
const ReportPaperPeek = reportPaperPeek.component
preloadWhen(() => isWide.value && broadsheetOn.value, reportPaperPeek.preload)
// 开合时版面变窄或变宽、条目跟着重排：把打开（收起）的那一条留在原来的高度，不让它跑出视野。换了内容时版面整个换掉，不留。
let keepPlace = true
watch(contentKey, () => {
  if (!peekTarget.value) return
  keepPlace = false
  peek.close()
})
watch(peekTarget, (next, previous) => {
  const keep = keepPlace
  keepPlace = true
  if (!keep || !next === !previous) return
  const shell = reportPageRef.value
  const key = (next ?? previous)?.key
  const item = Array.from(shell?.querySelectorAll<HTMLElement>('[data-list-key]') ?? []).find(el => el.dataset.listKey === key)
  if (!shell || !item) return
  const top = item.getBoundingClientRect().top
  void nextTick(() => {
    if (item.isConnected) shell.scrollTop += item.getBoundingClientRect().top - top
  })
}, { flush: 'pre' })
// 同一条讲到几篇时，在栏里换看另一篇
const pickPaper = (arxivId: string) => {
  if (peekTarget.value) peek.open({ key: peekTarget.value.key, arxivId })
}
const peekEnter = (el: Element, done: () => void) => slideIn(el, done, { x: 28 })
const peekLeave = (el: Element, done: () => void) => slideOut(el, done, { x: 28 })

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
// 收藏单独成包（components/report/desktopParts.ts），手机不下载；到了桌面大报版先取回来。
const ReportSavedPanel = reportSavedPanel.component
preloadWhen(broadsheetOn, reportSavedPanel.preload)
const savedView = ref(false)
watch(savedView, () => {
  contentKey.value += 1
  readingViewport.value?.scrollTo({ top: 0 })
})
// 换版面（紧凑的大报 ↔ 舒适的长文）时，把正在读的那一节留在控制条下原来的距离：两种版面都是一节一块（.report-section），
// 按第几节对上；控制条在两种版面里高矮不一，按它的底边量。位置按 offsetTop 量，不受换版面时内容淡入的位移影响。
// 收藏不是简报正文，离开大报版就回到简报开头。
const sectionBoxes = () => {
  const reading = reportRef.value
  if (!reading) return []
  const base = reading.getBoundingClientRect().top + reading.clientTop - reading.scrollTop
  return Array.from(reading.querySelectorAll<HTMLElement>('.report-section'), section => {
    let top = 0
    for (let node: HTMLElement | null = section; node && node !== reading; node = node.offsetParent as HTMLElement | null) top += node.offsetTop
    return { top: base + top, bottom: base + top + section.offsetHeight }
  })
}
watch(broadsheetOn, on => {
  if (savedView.value) {
    if (!on) savedView.value = false
    return
  }
  const viewport = readingViewport.value
  if (!isDesktop.value || !viewport || viewport.scrollTop < 1) return
  const readFrom = () => controlsRef.value?.getBoundingClientRect().bottom ?? viewport.getBoundingClientRect().top
  const from = readFrom()
  const boxes = sectionBoxes()
  const index = boxes.findIndex(box => box.bottom > from + 1)
  const before = boxes[index]?.top
  if (before == null) return
  void nextTick(() => {
    const after = sectionBoxes()[index]?.top
    if (after != null) viewport.scrollTop += after - readFrom() - (before - from)
  })
}, { flush: 'pre' })
const pickType = (type: ReportKey) => {
  selectedType.value = type
  savedView.value = false
}
const pickDate = (date: string) => {
  if (!date) return
  selectDate(date)
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
  <div
    ref="reportPageRef"
    class="report-shell flex h-full flex-col overflow-hidden p-4 gap-2.5"
    :class="{ 'has-peek': peekTarget }"
    :style="{ '--report-bar-h': `${Math.round(controlsHeight)}px`, '--report-view-h': `${Math.round(pageHeight)}px` }"
  >

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
        :reading-mode="broadsheetOn ? readingMode : null"
        :saved-count="broadsheetOn ? savedBriefing.count.value : null"
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
    <div ref="reportRef" v-swap="{ key: readingKey, stagger: true }" class="report-reading stagger-enter glass-card relative flex-1 min-h-0 overflow-y-auto scroll-smooth" style="animation-delay: 0.1s">
      <ReportSavedPanel v-if="savedView" :mode="readingMode" :peek="broadsheetPeek" />
      <ReportContentPanel
        v-else
        :report-content="reportContent"
        :is-generating="isGenerating"
        :is-preview="isPreview"
        :current-type-label="currentTypeInfo ? t(`report.type.${currentTypeInfo.labelKey}`) : ''"
        :auto-scroll="autoScroll"
        :render-markdown="renderMarkdown"
        :reading-mode="broadsheetOn ? readingMode : null"
        :content-key="contentKey"
        :saves="broadsheetOn ? briefingSaves : null"
        :peek="broadsheetPeek"
        :load-state="loadState"
        :issue-date="issueDate"
        :fallback-from="fallbackFrom"
        @resume-auto-scroll="resumeAutoScroll"
        @retry="retryLoad"
        @login="loginForFullReport"
      />
    </div>

    <!-- 宽屏：简报讲到的论文在右侧看详情 -->
    <Transition :css="false" @enter="peekEnter" @leave="peekLeave">
      <ReportPaperPeek
        v-if="peekTarget && peekPaper"
        :target="peekTarget"
        :state="peekPaper"
        :papers="peekEntry?.papers ?? []"
        :index="peekIndex"
        :total="peekEntries.length"
        :direction="peekDirection"
        :within-item="peekWithinItem"
        :render-markdown="renderMarkdown"
        @close="peek.close()"
        @step="peek.step($event)"
        @pick="pickPaper"
        @retry="peek.retry()"
      />
    </Transition>
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
