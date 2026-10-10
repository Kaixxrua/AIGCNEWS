<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import SpinnerLoader from '@/components/SpinnerLoader.vue'
import { reportBroadsheet } from '@/components/report/desktopParts'
import type { BroadsheetSaves, ReportReadingMode } from '@/components/report/ReportBroadsheet.vue'
import type { ReportLoadState } from '@/composables/useReportController'
import type { BroadsheetPeek } from '@/composables/useReportPeek'
import { parseBroadsheet } from '@/features/report/reportBroadsheet'
import { formatReportIssueDate, groupReportSections } from '@/features/report/reportViewModel'
import { preloadWhen } from '@/utils/lazyComponent'
const { t, locale } = useI18n()
const props = defineProps<{
  reportContent: string
  isGenerating: boolean
  isPreview?: boolean
  currentTypeLabel?: string
  autoScroll: boolean
  renderMarkdown: (content: string) => string
  /** 桌面（≥1024px）按大报版式排的阅读方式；不传时排成一列。 */
  readingMode?: ReportReadingMode | null
  /** 换了一期简报时变化，大报版式据此清掉上一期的展开状态。 */
  contentKey?: number
  /** 条目收藏（桌面大报版）；不给就没有书签。 */
  saves?: BroadsheetSaves | null
  /** 宽屏右侧的论文详情栏（≥1600px）；不给就没有。 */
  peek?: BroadsheetPeek | null
  /** 没有正文时阅读区说什么：读取中、今天的还没发布、那天没有、没读出来（可重试）；不传按读取中。 */
  loadState?: ReportLoadState
  /** 状态说的是哪一天（YYYY-MM-DD）。 */
  issueDate?: string
  /** 今天的还没出、先显示往前一期时为今天的日期，正文上方据此说明；其余时候为空。 */
  fallbackFrom?: string
}>()

const broadsheet = computed(() => props.readingMode && props.reportContent
  ? parseBroadsheet(props.renderMarkdown(props.reportContent))
  : null)

// 大报版式只在桌面出现，单独成包（components/report/desktopParts.ts），手机不下载；排成大报时先取回来，正文到了不用再等。
const ReportBroadsheet = reportBroadsheet.component
preloadWhen(() => Boolean(props.readingMode), reportBroadsheet.preload)

// 没有正文时的提示：读取中只说在读；今天的还没发布、那天没有、没读出来分开说
const emptyState = computed(() => {
  const type = props.currentTypeLabel ?? ''
  switch (props.loadState) {
    case 'pending':
      return { title: t('report.state.pendingToday', { type }), hint: t('report.state.pendingHint') }
    case 'missing':
      return { title: t('report.state.missing', { type, date: formatReportIssueDate(props.issueDate ?? '', locale.value) }), hint: t('report.state.missingHint') }
    case 'failed':
      return { title: t('report.state.failed'), hint: t('report.state.failedHint') }
    default:
      return { title: t('report.state.loading'), hint: '', busy: true }
  }
})

const emit = defineEmits<{
  resumeAutoScroll: []
  retry: []
  login: []
}>()
</script>

<template>
  <!-- 没有正文：读取中 / 今天的还没发布 / 那天没有 / 没读出来 -->
  <div v-if="!reportContent && !isGenerating" class="flex h-full flex-col items-center justify-center gap-2 text-stone-400 p-4" role="status" :aria-busy="emptyState.busy ? 'true' : undefined">
    <div class="flex h-12 w-12 items-center justify-center rounded-2xl bg-stone-100">
      <svg class="h-6 w-6 opacity-30" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/></svg>
    </div>
    <p class="text-sm font-medium text-stone-500 font-serif">{{ emptyState.title }}</p>
    <p v-if="emptyState.hint" class="text-xs text-center max-w-sm text-stone-400">{{ emptyState.hint }}</p>
    <button v-if="loadState === 'failed'" type="button" class="btn-secondary mt-1 px-3 py-1.5 text-xs" @click="emit('retry')">{{ t('report.state.retry') }}</button>
  </div>

  <!-- 生成中骨架 -->
  <div v-if="isGenerating && !reportContent" class="p-5">
    <div class="flex items-center gap-2 text-sm text-stone-500 mb-3">
      <span class="status-dot bg-cyan-500 animate-[pulseDot_2s_ease-in-out_infinite]" />
      {{ t('report.generatingType', { type: currentTypeLabel }) }}
    </div>
    <SpinnerLoader class="min-h-[200px]" />
  </div>

  <!-- 报告正文 -->
  <div v-if="reportContent" class="report-content p-5">
    <p v-if="fallbackFrom" class="report-fallback-notice mb-3 rounded-xl bg-stone-100 px-3 py-2 text-xs font-medium text-stone-600">{{ t('report.state.fallback', { type: currentTypeLabel, date: formatReportIssueDate(issueDate ?? '', locale) }) }}</p>
    <p class="report-ai-notice mb-3 inline-block rounded-full bg-stone-100 px-2.5 py-1 text-xs font-medium text-stone-600">{{ t('report.aiGeneratedNotice') }}</p>
    <ReportBroadsheet v-if="broadsheet" :key="contentKey" :sheet="broadsheet" :mode="readingMode ?? 'full'" :generating="isGenerating" :saves="saves" :peek="peek" />
    <article v-else class="prose-content prose-report max-w-none" v-html="groupReportSections(renderMarkdown(reportContent))" />
    <span v-if="isGenerating" class="inline-block h-4 w-0.5 animate-pulse bg-cyan-500 align-middle ml-0.5" />
    <div v-if="isPreview" class="mt-5 space-y-3" role="note">
      <p class="text-sm text-stone-500">{{ t('memberContent.reportHint') }}</p>
      <button type="button" class="btn-primary" @click="emit('login')">{{ t('memberContent.loginContinue') }}</button>
    </div>
  </div>

  <!-- {{ t('report.backToBottom') }}按钮 -->
  <button
    v-if="isGenerating && !autoScroll"
    class="sticky bottom-4 ml-auto mr-4 btn-primary text-xs"
    @click="emit('resumeAutoScroll')"
  >
    <svg class="h-3 w-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/></svg>
    {{ t('report.backToBottom') }}
  </button>
</template>
