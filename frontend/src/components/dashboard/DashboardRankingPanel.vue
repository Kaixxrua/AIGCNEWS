<script setup lang="ts">
import { computed } from 'vue'
import { projectDescription } from '@/features/projects/projectPresentation'
import { useMediaQuery } from '@vueuse/core'
import { useI18n } from 'vue-i18n'
import DashboardTweetPreview from './DashboardTweetPreview.vue'
import { displayTweetText } from '@/features/xboard/xBoardViewModel'
import RankingAvatar from './RankingAvatar.vue'
import ProjectHeat from '@/components/projects/ProjectHeat.vue'
import { ArrowDownWideNarrow, ArrowUpRight, CheckCircle2 } from 'lucide-vue-next'
import {
  TABS,
  aiScoreDisplay,
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

const { t, locale } = useI18n()
const displayDocs = computed(() => props.tabList.map(doc => {
  if (props.activeTab !== 'x' || !locale.value.toLowerCase().startsWith('zh') || !doc.translation_zh?.trim()) return doc
  const text = displayTweetText(doc, locale.value)
  return { ...doc, title: text, summary: text }
}))
const summary = (doc: TopDoc) => doc.source === 'github'
  ? projectDescription(doc, locale.value.startsWith('zh') ? 'zh-CN' : 'en-US', t('projects.fallbackProject'))
  : doc.summary
const isMobile = useMediaQuery('(max-width: 767px)')

const hasDistinctSummary = (doc: TopDoc) => Boolean(summary(doc)?.trim())
  && summary(doc)?.replace(/\s+/g, ' ').trim() !== doc.title?.replace(/\s+/g, ' ').trim()

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
    <div class="ranking-toolbar">
      <div class="ranking-tabs" role="tablist" :aria-label="t('dashboard.rankingSources')">
        <button v-for="tab in TABS" :id="`ranking-tab-${tab.key}`" :key="tab.key"
          type="button" class="ranking-tab" role="tab" aria-controls="ranking-content"
          :aria-selected="activeTab === tab.key" :aria-label="t(`dashboard.sources.${tab.labelKey}`)"
          :title="tab.key === 'hackernews' ? 'Hacker News' : undefined"
          @click="emit('selectSource', tab.key)">
          <component :is="tab.icon" class="ranking-tab-icon" :size="18" :stroke-width="1.75" aria-hidden="true" />
          <span>{{ t(`dashboard.sources.${tab.key === 'x' ? 'xCaption' : tab.labelKey}`) }}</span>
        </button>
      </div>
      <div v-if="!tabLoading" class="ranking-source-status flex items-center gap-2">
        <span v-if="boardDateHint" class="badge bg-card text-stone-500 border border-stone-200">{{ boardDateHint }}</span>
        <span v-if="activeTab === 'github' && tabList.length" class="ranking-sort" :title="t('projects.hotScoreTitle')"><ArrowDownWideNarrow :size="15" aria-hidden="true" />{{ t('dashboard.sortedByHeat') }}</span>
        <span class="ranking-live-status" role="status" :title="tabStatus?.isEmbargoed ? tabStatusHint || undefined : t((tabStatus?.isFinalized ?? isFinalized) ? 'dashboard.finalized' : 'dashboard.liveDraft')">
          <CheckCircle2 v-if="tabStatus?.isFinalized ?? isFinalized" :size="12" /><span v-else class="live-dot" />
          {{ tabStatus?.isEmbargoed ? tabStatusHint : t((tabStatus?.isFinalized ?? isFinalized) ? 'dashboard.tabFinalized' : 'dashboard.liveDraftShort') }}
        </span>
      </div>
    </div>

    <div id="ranking-content" class="ranking-list flex-1 overflow-y-auto" role="tabpanel" :aria-labelledby="`ranking-tab-${activeTab}`" :aria-busy="tabLoading">
      <div v-if="tabLoading" class="flex items-center justify-center py-8"><span class="inline-block h-5 w-5 rounded-full border-2 border-stone-200 border-t-stone-500 animate-spin" /></div>
      <div v-else-if="!tabList.length" class="flex flex-col items-center justify-center py-12 text-stone-400">
        <div class="w-12 h-12 mb-3 rounded-full bg-stone-100 flex items-center justify-center"><svg class="h-6 w-6 text-stone-300" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg></div>
        <p v-if="!isViewingHistory" class="text-sm font-medium text-stone-500">{{ t('dashboard.collecting') }}</p><p v-if="!isViewingHistory" class="mt-1 text-2xs text-stone-400">{{ t('dashboard.collectingHint') }}</p><p v-else class="text-sm font-medium text-stone-500">{{ t('dashboard.historyEmpty') }}</p><p v-if="isViewingHistory" class="mt-1 text-2xs text-stone-400">{{ t('dashboard.historyEmptyHint') }}</p>
      </div>
      <ol v-else :class="{ 'editorial-list': !(isMobile && activeTab === 'x') }">
        <li v-for="(doc, idx) in displayDocs" :key="doc.id ?? doc.url ?? idx" class="ranking-row group transition-colors duration-150" :class="{ 'ranking-row--featured': idx < 3, 'ranking-row--lead': idx === 0, 'ranking-row--silver': idx === 1, 'ranking-row--bronze': idx === 2 }">
          <svg v-if="idx < 3" class="ranking-ink-frame" viewBox="0 0 400 174" preserveAspectRatio="none" aria-hidden="true">
            <path class="ranking-ink-frame__outline" d="M8 2.5 390 1.5 Q398 1 398 9 L397.5 166 Q398 171.5 391 172 L8 171 Q2 172 2 165 L2.5 10 Q1.5 3 8 2.5Z" />
            <path class="ranking-ink-frame__trace" d="M9 4 186 3.5 M395 10 395.5 161 Q396 169 389 169.5 L246 169" />
            <path class="ranking-ink-frame__strokes" d="m9 163 19-16m-10 17 12-10M369 9l16-5m-9 13 17-10M7 60l10-12" />
          </svg>
          <DashboardTweetPreview v-if="isMobile && activeTab === 'x'" :doc="doc" :rank="idx + 1" />
          <a v-else :href="doc.url || undefined" :target="doc.url ? '_blank' : undefined" :rel="doc.url ? 'noopener noreferrer' : undefined" class="ranking-link flex items-start gap-2.5 px-4 py-1.5" :class="doc.url ? 'hover:bg-stone-50 cursor-pointer' : 'pointer-events-none'">
            <span class="ranking-number mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-2xs font-bold" :class="idx < 3 ? 'bg-ink-solid text-ink-on-solid' : 'bg-stone-100 text-stone-400'">{{ String(idx + 1).padStart(2, '0') }}</span>
            <RankingAvatar :doc="doc" :crowned="idx === 0" />
            <div class="ranking-body min-w-0 flex-1">
              <div class="flex flex-wrap items-start gap-2"><p class="ranking-title min-w-0 flex-1 text-sm font-medium text-stone-700 leading-tight group-hover:text-stone-900 line-clamp-2 sm:line-clamp-1" :class="doc.url ? 'group-hover:underline underline-offset-2' : ''">{{ doc.title || t('dashboard.untitled') }}</p><div class="ranking-badges flex shrink-0 items-center gap-1.5 ml-2"><span v-if="doc.ai_score !== undefined && doc.ai_score !== null" class="badge bg-card text-stone-600 border border-stone-200" :title="doc.ai_reason || t('dashboard.aiScore')">{{ aiScoreDisplay(doc.ai_score) }}</span><span class="badge border ranking-source-badge" :class="getSourceConfig(doc.source).badge"><span class="status-dot shrink-0" :class="getSourceConfig(doc.source).dot" />{{ getSourceConfig(doc.source).label }}</span></div></div>
              <p v-if="hasDistinctSummary(doc)" :title="summary(doc)" class="ranking-summary">{{ summary(doc) }}</p>
              <div class="ranking-meta mt-0.5 flex flex-wrap items-center gap-1.5"><ProjectHeat v-if="doc.source === 'github'" class="ranking-heat" :score="doc.hot_score" :available="doc.daily_growth_available" /><span v-if="doc.source === 'github' && doc.daily_growth_available && doc.daily_star_growth != null" class="ranking-growth">{{ t('projects.todayGrowth', { count: doc.daily_star_growth.toLocaleString(locale) }) }}</span><span class="ranking-score flex items-center gap-0.5 text-2xs text-stone-500 font-medium"><component :is="scoreDisplay(doc).icon" class="h-3 w-3 shrink-0" />{{ scoreDisplay(doc, value => value.toLocaleString()).text }}</span></div>
            </div>
            <ArrowUpRight v-if="doc.url" class="ranking-arrow" :size="18" />
          </a>
        </li>
      </ol>
    </div>
  </div>
</template>

<style scoped>
.dashboard-ranking-panel { display:flex;flex-direction:column;min-height:0;overflow:visible;padding:0;background:transparent;border:0;border-radius:0;box-shadow:none; }
.ranking-toolbar { display:flex;align-items:center;justify-content:space-between;flex:0 0 51px;min-width:0;margin-bottom:9px; }
.ranking-tabs { display:flex;min-width:0;align-self:stretch; }
/* One outline per tab; separators belong only between unselected tabs. */
.ranking-tab { position:relative;isolation:isolate;display:inline-flex;align-items:center;justify-content:center;gap:9px;padding:7px 20px;color:var(--ink);font-size:18px;font-weight:650;white-space:nowrap; }
.ranking-tab:not([aria-selected='true']) + .ranking-tab:not([aria-selected='true'])::before { content:'';position:absolute;left:0;height:26px;width:1px;background:var(--rule);transform:skew(-18deg); }
.ranking-tab:not([aria-selected='true'])::after { content:'';position:absolute;inset:0;z-index:-1;border-radius:7px;transform:skewX(-10deg);pointer-events:none; }
.ranking-tab:not([aria-selected='true']):is(:hover,:focus-visible)::after { background:var(--paper-muted); }
.ranking-tab[aria-selected='true'] { margin-right:5px;padding-inline:25px;color:var(--acid-ink);font-size:23px;font-weight:850; }
.ranking-tab[aria-selected='true']::after { content:'';position:absolute;inset:0;z-index:-1;border:1.5px solid var(--rule-strong);border-radius:7px;background:var(--acid);transform:skewX(-10deg); }
.ranking-tab:focus-visible,.ranking-link:focus-visible { outline:2px solid var(--ink);outline-offset:-3px; }
.ranking-tab-icon { width:25px;height:25px;flex-shrink:0; }
.ranking-source-status { gap:14px;padding:0 9px;flex-shrink:0; }
.ranking-sort { display:flex;align-items:center;gap:5px;color:var(--ink-secondary);font-size:13px;font-weight:650;white-space:nowrap;cursor:help; }
.ranking-live-status { display:flex;align-items:center;gap:7px;border:1px solid var(--rule-strong);border-radius:30px;padding:6px 10px;font-size:13px;font-weight:650;color:var(--ink);white-space:nowrap; }
.live-dot { flex-shrink:0;width:8px;height:8px;margin:3px;background:var(--live-dot);border-radius:50%;box-shadow:0 0 0 3px var(--live-dot-halo); }
.ranking-list { flex:1;min-height:0;overflow:auto; }
.editorial-list { display:grid;grid-template-columns:repeat(3,minmax(0,1fr));grid-template-rows:172px repeat(7,minmax(0,1fr));gap:6px 10px;height:100%; }
.ranking-row { min-width:0;border:1px solid var(--rule);border-radius:7px;background:var(--paper-raised);overflow:hidden; }
.ranking-link { position:relative;display:flex;align-items:center;gap:14px;height:100%;min-height:0;padding:3px 12px;color:var(--ink); }
.ranking-link:hover { background:color-mix(in srgb,var(--acid) 7%,transparent); }
.ranking-number { display:flex;justify-content:center;flex:0 0 38px;width:38px;height:auto;margin:0;background:none;color:var(--ink-secondary);font-size:23px;line-height:1;font-weight:850;font-style:italic;font-variant-numeric:tabular-nums; }
.ranking-link :deep(.ranking-avatar) { width:42px;height:42px;flex-basis:42px; }
.ranking-body { min-width:0;flex:1; }
.ranking-title { display:block;overflow:hidden;color:var(--ink);font-size:15px;line-height:1.4;font-weight:750;white-space:nowrap;text-overflow:ellipsis; }
.ranking-summary { display:-webkit-box;-webkit-line-clamp:1;-webkit-box-orient:vertical;overflow:hidden;margin:1px 0 0;color:var(--ink-secondary);font-size:13px;line-height:1.5; }
.ranking-badges { display:none; }
.ranking-meta { display:flex;align-items:center;gap:14px;margin:0;flex-wrap:nowrap; }
.ranking-growth { color:var(--growth-ink);font-size:13px;font-weight:650;white-space:nowrap; }
.ranking-row .ranking-heat { gap:4px;font-size:15px;font-weight:800;white-space:nowrap; }
.ranking-heat :deep(svg) { width:15px;height:15px; }
.ranking-score { display:flex;align-items:center;gap:6px;color:var(--ink-secondary);font-size:13px;font-weight:650;white-space:nowrap; }
.ranking-score svg { width:17px;height:17px; }
.ranking-arrow { flex-shrink:0;width:23px;height:23px;color:var(--ink-muted); }

/* Rows 4–10: copy on the left, one aligned metric grid on the right. */
.ranking-row:not(.ranking-row--featured) { grid-column:1/-1; }
.ranking-row:not(.ranking-row--featured) .ranking-body { display:grid;grid-template-columns:minmax(0,1fr) auto;column-gap:12px;align-items:center; }
.ranking-row:not(.ranking-row--featured) .ranking-summary { grid-column:1;grid-row:2; }
.ranking-row:not(.ranking-row--featured) .ranking-meta { grid-column:2;grid-row:1/3;display:grid;grid-template-columns:100px 78px 80px;gap:12px;align-items:center;font-variant-numeric:tabular-nums; }
.ranking-row:not(.ranking-row--featured) .ranking-heat { grid-column:1;justify-self:start; }
.ranking-row:not(.ranking-row--featured) .ranking-growth { grid-column:2;text-align:right; }
.ranking-row:not(.ranking-row--featured) .ranking-score { grid-column:3;display:grid;grid-template-columns:17px 1fr;gap:6px;text-align:right; }

/* Podium cards 1–3: gold, cool silver, copper — hue carries rank, ink stays readable. */
.ranking-row--featured { position:relative;isolation:isolate;border:2px solid transparent;border-radius:6px;background:linear-gradient(135deg,color-mix(in srgb,var(--podium) 23%,var(--paper-raised)),var(--paper-raised) 60%,color-mix(in srgb,var(--podium) 25%,var(--paper-raised))); }
.ranking-row--lead { --podium:var(--podium-gold);--podium-ink:var(--podium-gold-ink); }
.ranking-row--silver { --podium:var(--podium-silver);--podium-ink:var(--podium-silver-ink); }
.ranking-row--bronze { --podium:var(--podium-bronze);--podium-ink:var(--podium-bronze-ink); }
.ranking-row--featured::before { content:'';position:absolute;inset:3px;z-index:-1;pointer-events:none;background-image:radial-gradient(color-mix(in srgb,var(--podium) 78%,var(--podium-ink)) .65px,transparent .85px);background-size:3px 3px;mask-image:linear-gradient(135deg,#000,transparent 26%,transparent 76%,#000);opacity:.8; }
.ranking-row--featured::after { content:'';position:absolute;inset:3px;z-index:-1;pointer-events:none;background:linear-gradient(138deg,transparent 0 12%,color-mix(in srgb,var(--podium) 45%,transparent) 12% 13%,transparent 13% 16%,color-mix(in srgb,var(--podium) 23%,transparent) 16% 18%,transparent 18% 81%,color-mix(in srgb,var(--podium) 35%,transparent) 81% 82%,transparent 82% 89%,color-mix(in srgb,var(--podium) 48%,transparent) 89% 90%,transparent 90%);clip-path:polygon(0 0,40% 0,0 57%,0 100%,68% 100%,100% 36%,100% 100%,0 100%); }
.ranking-ink-frame { position:absolute;inset:-2px;z-index:2;width:calc(100% + 4px);height:calc(100% + 4px);pointer-events:none;fill:none;stroke-linecap:round;stroke-linejoin:round; }
.ranking-ink-frame path { vector-effect:non-scaling-stroke; }
.ranking-ink-frame__outline { stroke:var(--rule-strong);stroke-width:1.8; }
.ranking-ink-frame__trace { stroke:var(--rule-strong);stroke-width:.65;opacity:.45; }
.ranking-ink-frame__strokes { stroke:var(--podium);stroke-width:1.2;opacity:.85; }
.ranking-row--silver .ranking-ink-frame { transform:scaleX(-1); }
.ranking-row--featured .ranking-link { gap:13px;padding:48px 13px 11px; }
.ranking-row--featured .ranking-number { position:absolute;left:16px;top:9px;color:var(--podium-ink);font-size:38px;line-height:1;font-weight:950;text-shadow:1px 2px 0 var(--paper-raised);transform:skewX(-4deg); }
.ranking-row--featured .ranking-link :deep(.ranking-avatar) { width:78px;height:78px;flex-basis:78px;border:0; }
.ranking-row--featured .ranking-title { font-size:16px;letter-spacing:-.035em; }
.ranking-row--featured .ranking-summary { -webkit-line-clamp:2;margin:6px 0 11px;font-size:13px;line-height:1.55; }
.ranking-row--featured .ranking-meta { gap:17px; }
.ranking-row--featured .ranking-growth { font-size:15px; }
.ranking-row--featured .ranking-heat { position:absolute;top:14px;right:44px;font-size:19px; }
.ranking-row--featured .ranking-heat :deep(svg) { width:18px;height:18px; }
.ranking-row--featured .ranking-score { font-size:16px; }
.ranking-row--featured .ranking-arrow { position:absolute;top:16px;right:12px;color:var(--podium-ink); }

:root[data-theme='dark'] .ranking-row--featured { background:linear-gradient(135deg,color-mix(in srgb,var(--podium) 5%,var(--paper-raised)),var(--paper-raised)); }
:root[data-theme='dark'] .ranking-row--featured::before { opacity:.12; }
:root[data-theme='dark'] .ranking-row--featured::after { opacity:.4; }
:root[data-theme='dark'] .ranking-ink-frame__outline { stroke:var(--rule);stroke-width:1; }
:root[data-theme='dark'] .ranking-ink-frame__trace { opacity:.2; }
:root[data-theme='dark'] .ranking-ink-frame__strokes { opacity:.3; }
:root[data-theme='dark'] .ranking-number { text-shadow:none; }

@media (max-width:1499px) {
  .ranking-tab { gap:6px;padding-inline:12px;font-size:15px; }
  .ranking-tab[aria-selected='true'] { padding-inline:18px;font-size:19px; }
  .ranking-tab-icon { width:21px;height:21px; }
  .ranking-live-status { padding:5px 7px;font-size:11px; }
  .ranking-source-status { gap:10px; }
  .ranking-sort { font-size:12px; }
  .ranking-link { gap:9px;padding-inline:9px; }
  .ranking-number { flex-basis:30px; }
  .ranking-summary { font-size:11px; }
  .ranking-meta { gap:9px; }
  .ranking-growth,.ranking-score { font-size:12px; }
  .ranking-row .ranking-heat { font-size:13px; }
  .ranking-row:not(.ranking-row--featured) .ranking-meta { grid-template-columns:84px 68px 71px;gap:8px; }
  .ranking-row--featured .ranking-link { gap:9px;padding-inline:10px; }
  .ranking-row--featured .ranking-link :deep(.ranking-avatar) { width:58px;height:58px;flex-basis:58px; }
  .ranking-row--featured .ranking-title { font-size:13px; }
  .ranking-row--featured .ranking-summary { font-size:12px; }
  .ranking-row--featured .ranking-heat { font-size:16px; }
  .ranking-row--featured .ranking-score { font-size:14px; }
}
@media (max-width:1199px) {
  .ranking-toolbar { flex-wrap:wrap;gap:8px;padding-bottom:5px; }
  .ranking-tabs { flex:1;justify-content:space-between; }
  .ranking-source-status { margin-left:auto; }
  .ranking-list { overflow:visible; }
  .editorial-list { height:auto;grid-template-rows:175px repeat(7,minmax(58px,auto)); }
  .ranking-row:not(.ranking-row--featured) .ranking-body { display:block; }
  .ranking-row:not(.ranking-row--featured) .ranking-meta { margin-top:3px; }
  .ranking-row--featured .ranking-link :deep(.ranking-avatar) { width:48px;height:48px;flex-basis:48px; }
}
@media (min-width:1024px) and (max-height:820px) {
  .editorial-list { grid-template-rows:136px repeat(7,minmax(0,1fr)); }
  .ranking-link { gap:8px;padding-block:1px; }
  .ranking-link :deep(.ranking-avatar) { width:32px;height:32px;flex-basis:32px; }
  .ranking-number { font-size:22px;flex-basis:30px; }
  .ranking-title { font-size:12px;line-height:1.25; }
  .ranking-summary { font-size:11px;line-height:1.3; }
  .ranking-row--featured .ranking-link { padding:39px 10px 7px; }
  .ranking-row--featured .ranking-number { font-size:33px; }
  .ranking-row--featured .ranking-link :deep(.ranking-avatar) { width:49px;height:49px;flex-basis:49px; }
  .ranking-row--featured .ranking-title { font-size:12px; }
  .ranking-row--featured .ranking-summary { margin:4px 0 6px;font-size:11px;line-height:1.4; }
  .ranking-row--featured .ranking-meta { gap:8px; }
  .ranking-row--featured .ranking-growth { font-size:12px; }
  .ranking-row--featured .ranking-heat { top:11px;font-size:15px; }
  .ranking-row--featured .ranking-score { font-size:13px; }
  .ranking-row--featured .ranking-arrow { top:11px; }
}
</style>
