<script setup lang="ts">
import { computed } from 'vue'
import { useMediaQuery } from '@vueuse/core'
import { useI18n } from 'vue-i18n'
import DashboardTweetPreview from './DashboardTweetPreview.vue'
import RankingAvatar from './RankingAvatar.vue'
import { CheckCircle2, Zap } from 'lucide-vue-next'
import {
  TABS,
  aiScoreDisplay,
  getModuleTags,
  getSourceConfig,
  getTabBoardStatus,
  scoreDisplay,
  tabBoardStatusHint,
  type TabKey,
  type TopDoc,
} from '@/features/dashboard/dashboardViewModel'
import type { SourceStatusMap } from '@/services/dashboard/dashboardContracts'

const props = defineProps<{
  activeTab: TabKey
  tabList: TopDoc[]
  tabLoading: boolean
  isViewingHistory: boolean
  isFinalized: boolean
  sourceStatus: SourceStatusMap
}>()

const { t } = useI18n()
const isMobile = useMediaQuery('(max-width: 767px)')

const hasDistinctSummary = (doc: TopDoc) => Boolean(doc.summary?.trim())
  && doc.summary?.replace(/\s+/g, ' ').trim() !== doc.title?.replace(/\s+/g, ' ').trim()

const emit = defineEmits<{
  selectSource: [key: TabKey]
}>()

// 分源定稿状态（PR6）：当前 tab 按自己的源日界/定稿时刻揭榜，
// 取代整榜一刀切标签；wire 缺省（旧后端）时不渲染徽章。
const tabStatus = computed(() => getTabBoardStatus(props.sourceStatus, props.activeTab))
const tabStatusHint = computed(() =>
  tabStatus.value ? tabBoardStatusHint(tabStatus.value, t) : null,
)

// Product Hunt 榜日透出：条目 published_date 即 featuredAt 的太平洋日期，
// 与快照日可能不同（CST 上午展示的仍是 PT 昨日榜）。
const boardDateHint = computed(() => {
  if (props.activeTab !== 'producthunt') return null
  const boardDate = props.tabList.find(doc => doc.published_date)?.published_date
  return boardDate ? t('dashboard.boardDate', { date: boardDate }) : null
})
</script>

<template>
  <div class="dashboard-ranking-panel stagger-enter glass-card flex-1 min-h-0 flex flex-col overflow-hidden" style="animation-delay: 0.6s">
    <div class="ranking-toolbar flex flex-wrap items-center justify-between gap-2 px-4 py-2" style="border-bottom: 1px solid rgb(var(--stone-400-rgb) / 0.15)">
      <div class="ranking-tabs flex gap-1" role="tablist" :aria-label="t('dashboard.rankingSources')">
        <button v-for="tab in TABS" :key="tab.key" class="flex items-center gap-1 rounded-full px-3 py-1 text-xs font-medium transition-all duration-200" :class="activeTab === tab.key ? 'tab-active' : 'tab-inactive'" role="tab" :aria-selected="activeTab === tab.key" @click="emit('selectSource', tab.key)">
          <component :is="tab.icon" class="h-3.5 w-3.5" />{{ t(`dashboard.stats.${tab.labelKey}`) }}
        </button>
      </div>
      <div v-if="boardDateHint || (tabStatus && tabStatusHint)" class="ranking-source-status flex items-center gap-2">
        <span v-if="boardDateHint" class="badge bg-card text-stone-500 border border-stone-200">{{ boardDateHint }}</span>
        <span v-if="tabStatus && tabStatusHint" class="flex items-center gap-1 text-2xs" :class="tabStatus.isFinalized ? 'text-emerald-600' : 'text-amber-600'" role="status">
          <CheckCircle2 v-if="tabStatus.isFinalized" class="h-3 w-3 shrink-0" /><Zap v-else class="h-3 w-3 shrink-0" :class="tabStatus.isEmbargoed ? '' : 'animate-pulse'" />{{ tabStatusHint }}
        </span>
      </div>
    </div>

    <div v-if="!isFinalized && !tabLoading" class="flex items-center gap-2 px-4 py-1 text-xs" style="border-bottom: 1px solid var(--notice-warn-border); background: var(--notice-warn-bg)"><Zap class="h-3.5 w-3.5 animate-pulse text-amber-500"/><span class="text-stone-600">{{ t('dashboard.liveDraft') }}</span></div>
    <div v-else-if="isFinalized && !tabLoading" class="flex items-center gap-2 px-4 py-1 text-xs" style="border-bottom: 1px solid var(--notice-ok-border); background: var(--notice-ok-bg)"><CheckCircle2 class="h-3.5 w-3.5 text-emerald-500"/><span class="text-stone-400">{{ t('dashboard.finalized') }}</span></div>

    <div class="ranking-list flex-1 overflow-y-auto">
      <div v-if="tabLoading" class="flex items-center justify-center py-8"><span class="inline-block h-5 w-5 rounded-full border-2 border-stone-200 border-t-stone-500 animate-spin" /></div>
      <div v-else-if="!tabList.length" class="flex flex-col items-center justify-center py-12 text-stone-400">
        <div class="w-12 h-12 mb-3 rounded-full bg-stone-100 flex items-center justify-center"><svg class="h-6 w-6 text-stone-300" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg></div>
        <p v-if="!isViewingHistory" class="text-sm font-medium text-stone-500">{{ t('dashboard.collecting') }}</p><p v-if="!isViewingHistory" class="mt-1 text-2xs text-stone-400">{{ t('dashboard.collectingHint') }}</p><p v-else class="text-sm font-medium text-stone-500">{{ t('dashboard.historyEmpty') }}</p><p v-if="isViewingHistory" class="mt-1 text-2xs text-stone-400">{{ t('dashboard.historyEmptyHint') }}</p>
      </div>
      <ol v-else :class="{ 'editorial-list': !(isMobile && activeTab === 'x') }">
        <li v-for="(doc, idx) in tabList" :key="idx" class="ranking-row group transition-colors duration-150" :class="{ 'ranking-row--featured': idx < 3, 'ranking-row--lead': idx === 0 }">
          <DashboardTweetPreview v-if="isMobile && activeTab === 'x'" :doc="doc" :rank="idx + 1" />
          <a v-else :href="doc.url || undefined" :target="doc.url ? '_blank' : undefined" :rel="doc.url ? 'noopener noreferrer' : undefined" class="ranking-link flex items-start gap-2.5 px-4 py-1.5" :class="doc.url ? 'hover:bg-stone-50 cursor-pointer' : 'pointer-events-none'">
            <span class="ranking-number mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-2xs font-bold" :class="idx < 3 ? 'bg-ink-solid text-ink-on-solid' : 'bg-stone-100 text-stone-400'">{{ String(idx + 1).padStart(2, '0') }}</span>
            <RankingAvatar :doc="doc" />
            <div class="ranking-body min-w-0 flex-1">
              <div class="flex flex-wrap items-start gap-2"><p class="ranking-title min-w-0 flex-1 text-sm font-medium text-stone-700 leading-tight group-hover:text-stone-900 line-clamp-2 sm:line-clamp-1" :class="doc.url ? 'group-hover:underline underline-offset-2' : ''">{{ doc.title || t('dashboard.untitled') }}</p><div class="ranking-badges flex shrink-0 items-center gap-1.5 ml-2"><span v-if="doc.ai_score !== undefined && doc.ai_score !== null" class="badge bg-card text-stone-600 border border-stone-200" :title="doc.ai_reason || t('dashboard.aiScore')">{{ aiScoreDisplay(doc.ai_score) }}</span><span class="badge border ranking-source-badge" :class="getSourceConfig(doc.source).badge"><span class="status-dot shrink-0" :class="getSourceConfig(doc.source).dot" />{{ getSourceConfig(doc.source).label }}</span></div></div>
              <p v-if="hasDistinctSummary(doc)" class="ranking-summary">{{ doc.summary }}</p>
              <div class="ranking-meta mt-0.5 flex flex-wrap items-center gap-1.5"><span class="flex items-center gap-0.5 text-2xs text-stone-500 font-medium"><component :is="scoreDisplay(doc).icon" class="h-3 w-3 shrink-0" />{{ scoreDisplay(doc, value => value.toLocaleString()).text }}</span><span v-if="doc.language" class="badge bg-card text-stone-500 border border-stone-200">{{ doc.language }}</span><span v-for="tag in getModuleTags(doc)" :key="tag" class="badge bg-card text-stone-500 border border-stone-200">{{ tag }}</span></div>
            </div>
            <svg v-if="doc.url" class="mt-1 h-3.5 w-3.5 shrink-0 text-stone-300 opacity-0 group-hover:opacity-100 transition-opacity" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>
          </a>
        </li>
      </ol>
    </div>
  </div>
</template>

<style scoped>
.ranking-summary { display: none; }
.tab-active { border: 1px solid var(--ink); border-radius: 4px; color: var(--projects-on-acid); background: var(--acid); box-shadow: none; }
.tab-inactive { border: 1px solid transparent; border-radius: 4px; color: var(--ink); }
.tab-inactive:hover { border-color: var(--ink); color: var(--ink); background: var(--acid-soft); }
ol > li { border-top: 1px solid var(--rule) !important; background: transparent; }
ol > li:first-child { border-top: 0 !important; }
ol > li a:hover { color: var(--ink); background: var(--acid-soft); }
ol > li a:hover :deep(.text-stone-700), ol > li a:hover :deep(.text-stone-500), ol > li a:hover :deep(.text-stone-300) { color: inherit; }
/* 榜单行内徽章紧凑化：10 条榜单一屏放下 */
:deep(.badge) { border-color: var(--badge-default-border); border-radius: 3px; background: var(--badge-default-bg); padding: 0 5px; font-size: 10px; line-height: 16px; }
.ranking-title { color: var(--ink); font-weight: 600; }
.ranking-link:focus-visible { outline: 2px solid var(--ink); outline-offset: -3px; background: var(--acid-soft); }
.ranking-link:focus-visible .ranking-title { text-decoration: underline; text-underline-offset: 3px; }
.ranking-link:focus-visible > svg { opacity: 1; }
@media (min-width: 768px) {
  .ranking-title { font-size: 15px; line-height: 20px; }
  .ranking-link { padding-block: 4px; }
  .ranking-number { margin-top: 0; font-variant-numeric: tabular-nums; }
  .ranking-meta { column-gap: 8px; }
  .ranking-meta > span:first-child { color: var(--ink-secondary); }
}

@media (max-width: 1023px) {
  .ranking-list { flex: none; overflow: visible; }
}

@media (max-width: 767px) {
  [role='tablist'] { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); width: 100%; overflow: visible; }
  [role='tab'] { min-width: 0; justify-content: center; min-height: 44px; font-size: 14px; white-space: nowrap; }
  .ranking-link { gap: 10px; padding: 16px 12px; }
  .ranking-link p { font-size: 16px; line-height: 1.55; overflow-wrap: anywhere; }
  :deep(.badge) { font-size: 11px; line-height: 20px; }
}
.ranking-tabs { min-width: 0; max-width: 100%; flex-wrap: wrap; }
.ranking-tabs button { min-height: 32px; }
.ranking-tabs button:focus-visible { outline: 2px solid var(--ink); outline-offset: 2px; }
@media (max-width: 1023px) { .ranking-tabs button { min-height: 44px; } }

/* Editorial cards share the same ordered list and links as compact rows. */
.dashboard-ranking-panel { flex: none; overflow: visible; padding: 12px; }
.ranking-toolbar { padding: 0 0 12px; border-bottom: 0 !important; }
.ranking-tabs { gap: 6px; }
.ranking-tabs button { border-radius: 9px; padding: 9px 16px; min-height: 38px; }
.tab-active { border-color: transparent; box-shadow: none; }
.tab-inactive { border-color: var(--rule); }
.ranking-list { overflow: visible; flex: none; }
.editorial-list { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; padding-top: 12px; }
.editorial-list > .ranking-row { min-width: 0; border: 1px solid var(--rule) !important; border-radius: 9px; background: var(--paper-light); overflow: hidden; }
.editorial-list > .ranking-row:not(.ranking-row--featured) { grid-column: 1 / -1; }
.editorial-list .ranking-link { position: relative; align-items: center; gap: 12px; padding: 10px 12px; min-height: 52px; height: 100%; }
.editorial-list .ranking-number { flex: 0 0 24px; font-size: 14px; font-weight: 500; background: transparent; color: var(--muted); }
.editorial-list .ranking-title { font-size: 13px; line-height: 1.5; font-weight: 700; overflow-wrap: anywhere; }
.editorial-list .ranking-summary { display: -webkit-box; -webkit-line-clamp: 1; -webkit-box-orient: vertical; overflow: hidden; color: var(--muted); font-size: 12px; line-height: 1.65; margin: 4px 0; }
.editorial-list .ranking-meta { gap: 6px; }
.editorial-list .ranking-meta > span:first-child { font-size: 12px; color: inherit; }
.editorial-list .ranking-source-badge { display: none; }
.editorial-list .ranking-badges { margin-left: 0; }
.editorial-list .ranking-link > svg { opacity: 1; color: var(--muted); margin: 0; width: 14px; height: 14px; }
.editorial-list .ranking-row--featured .ranking-link { min-height: 170px; padding: 48px 14px 16px; align-items: start; gap: 12px; }
.editorial-list .ranking-row--featured .ranking-number { position: absolute; left: 16px; top: 15px; font-size: 20px; font-weight: 750; color: var(--ink); }
.editorial-list .ranking-row--featured .ranking-link > svg { position: absolute; right: 16px; top: 17px; width: 18px; height: 18px; }
.editorial-list .ranking-row--featured :deep(.ranking-avatar) { width: 58px; height: 58px; flex-basis: 58px; font-size: 22px; }
.editorial-list .ranking-row--featured .ranking-title { -webkit-line-clamp: 2; font-size: 14px; }
.editorial-list .ranking-row--featured .ranking-summary { -webkit-line-clamp: 2; margin: 7px 0 10px; }
.editorial-list > .ranking-row--lead { background: radial-gradient(ellipse at top left, #293c2b, transparent 70%), #131916; color: #f4f5ed; border-color: #19261b !important; }
.editorial-list .ranking-row--lead .ranking-title { color: #f4f5ed; }
.editorial-list .ranking-row--lead .ranking-summary { color: #bbc8b8; }
.editorial-list .ranking-row--lead .ranking-number, .editorial-list .ranking-row--lead .ranking-link > svg { color: #d6fb53; }
.editorial-list .ranking-row--lead :deep(.badge) { background: #ffffff12; color: #d5dfd2; border-color: #ffffff0a; }
.editorial-list .ranking-row--lead .ranking-link:hover, .editorial-list .ranking-row--lead .ranking-link:focus-visible { background: #ffffff08; color: #f4f5ed; }
.editorial-list .ranking-row--lead .ranking-link:focus-visible { outline-color: #d6fb53; }
@media (min-width: 1500px) {
  .editorial-list .ranking-row:not(.ranking-row--featured) .ranking-body { display: grid; grid-template-columns: minmax(210px, 1fr) minmax(180px, 1.2fr) 190px; align-items: center; gap: 16px; }
  .editorial-list .ranking-row:not(.ranking-row--featured) .ranking-summary { margin: 0; }
  .editorial-list .ranking-row:not(.ranking-row--featured) .ranking-meta { max-width: 220px; justify-content: flex-end; }
}
@media (min-width: 900px) and (max-width: 1249px) {
  .editorial-list .ranking-row--featured .ranking-link { display: block; padding: 42px 12px 14px; }
  .editorial-list .ranking-row--featured :deep(.ranking-avatar) { width: 42px; height: 42px; margin-bottom: 10px; }
}
@media (max-width: 639px) {
  .editorial-list { grid-template-columns: minmax(0, 1fr); }
  .editorial-list .ranking-row--featured .ranking-link { min-height: 160px; }
  .editorial-list .ranking-title { font-size: 14px; }
  .editorial-list .ranking-link { gap: 9px; }
  .ranking-tabs button { padding: 9px; min-height: 44px; }
  .ranking-source-status { font-size: 11px; }
}
</style>
