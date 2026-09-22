<script setup lang="ts">
import { computed } from 'vue'
import { projectDescription } from '@/features/projects/projectPresentation'
import { useMediaQuery } from '@vueuse/core'
import { useI18n } from 'vue-i18n'
import DashboardTweetPreview from './DashboardTweetPreview.vue'
import { displayTweetText } from '@/features/xboard/xBoardViewModel'
import RankingAvatar from './RankingAvatar.vue'
import ProjectHeat from '@/components/projects/ProjectHeat.vue'
import { ArrowUpRight, CheckCircle2 } from 'lucide-vue-next'
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
              <div class="ranking-meta mt-0.5 flex flex-wrap items-center gap-1.5"><span v-if="doc.source === 'github' && doc.daily_growth_available && doc.daily_star_growth != null" class="ranking-growth">{{ t('projects.todayGrowth', { count: doc.daily_star_growth.toLocaleString(locale) }) }}</span><ProjectHeat v-if="doc.source === 'github'" class="ranking-heat" :score="doc.hot_score" :available="doc.daily_growth_available" /><span class="ranking-score flex items-center gap-0.5 text-2xs text-stone-500 font-medium"><component :is="scoreDisplay(doc).icon" class="h-3 w-3 shrink-0" />{{ scoreDisplay(doc, value => value.toLocaleString()).text }}</span></div>
            </div>
            <ArrowUpRight v-if="doc.url" class="ranking-arrow" :size="18" />
          </a>
        </li>
      </ol>
    </div>
  </div>
</template>

<style scoped>

.dashboard-ranking-panel { display:flex; flex-direction:column; min-height:0; overflow:visible; padding:0; background:transparent; border:0; border-radius:0; box-shadow:none; }
.ranking-toolbar { display:flex; align-items:center; justify-content:space-between; flex:0 0 51px; min-width:0; margin-bottom:9px; border:1.5px solid var(--rule-strong); border-radius:9px; background:var(--paper-raised); }
.ranking-tabs { display:flex; min-width:0; align-self:stretch; }
.ranking-tab { position:relative; display:inline-flex; align-items:center; justify-content:center; gap:9px; padding:7px 20px; color:var(--ink); font-size:18px; font-weight:650; white-space:nowrap; }
.ranking-tab + .ranking-tab:not([aria-selected='true'])::before { content:''; position:absolute; left:0; height:26px; width:1px; background:var(--rule); transform:skew(-18deg); }
.ranking-tab-icon { width:25px;height:25px;flex-shrink:0; }
.ranking-tab[aria-selected='true'] { background:var(--acid); color:var(--acid-ink); border:1.5px solid var(--rule-strong); border-radius:8px; transform:skew(-10deg); margin:-1.5px 5px -1.5px -1.5px; padding-inline:25px; font-size:23px; font-weight:850; }
.ranking-tab[aria-selected='true'] > * { transform:skew(10deg); }
.ranking-tab:hover:not([aria-selected='true']) { background:transparent; }
.ranking-tab:not([aria-selected='true'])::after { content:'';position:absolute;inset:0;z-index:-1;border-radius:7px;transform:skewX(-10deg);pointer-events:none; }
.ranking-tab:not([aria-selected='true']):is(:hover,:focus-visible)::after { background:var(--paper-muted); }
.ranking-tab:focus-visible,.ranking-link:focus-visible { outline:2px solid var(--acid); outline-offset:-3px; }
.ranking-source-status { padding:0 9px;flex-shrink:0; }
.ranking-live-status { display:flex;align-items:center;gap:7px;border:1px solid var(--rule-strong);border-radius:30px;padding:6px 10px;font-size:13px;font-weight:650;color:var(--ink);white-space:nowrap; }
.live-dot { width:13px;height:13px;border:3px solid var(--acid);background:var(--ink);border-radius:50%; }
.ranking-list { flex:1;min-height:0;overflow:auto; }
.editorial-list { display:grid;grid-template-columns:repeat(3,minmax(0,1fr));grid-template-rows:172px repeat(7,minmax(46px,1fr));gap:6px 10px;height:100%; }
.ranking-row { min-width:0;border:1px solid var(--rule);border-radius:7px;background:var(--paper-raised);overflow:hidden; }
.ranking-row:not(.ranking-row--featured) { grid-column:1/-1; }
.ranking-row:nth-child(4) { margin-top:0; }
.ranking-link { position:relative;display:flex;align-items:center;gap:14px;height:100%;min-height:46px;padding:3px 12px;color:var(--ink); }
.ranking-link:hover { background:color-mix(in srgb,var(--acid) 7%,transparent); }
.ranking-number { display:flex;justify-content:center;flex:0 0 38px;width:38px;height:auto;margin:0;background:none;color:var(--ink-secondary);font-size:23px;line-height:1;font-weight:850;font-style:italic;font-variant-numeric:tabular-nums; }
.ranking-link :deep(.ranking-avatar) { width:42px;height:42px;flex-basis:42px; }
.ranking-body { min-width:0;flex:1; }
.ranking-title { color:var(--ink);font-size:15px;line-height:1.4;font-weight:750;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;display:block; }
.ranking-summary { display:-webkit-box;-webkit-line-clamp:1;-webkit-box-orient:vertical;overflow:hidden;color:var(--ink-secondary);font-size:13px;line-height:1.5;margin:1px 0 0; }
.ranking-badges { display:none; }
.ranking-meta { display:flex;align-items:center;gap:14px;margin:0;flex-wrap:nowrap; }
.ranking-growth { color:#087425;font-size:14px;font-weight:750;white-space:nowrap; }
.ranking-score { display:flex;align-items:center;gap:6px;color:var(--ink);font-size:14px;font-weight:750;white-space:nowrap; }
.ranking-score svg { width:21px;height:21px; }
.ranking-heat { color:#ef4829;white-space:nowrap; }
.ranking-arrow { flex-shrink:0;width:23px;height:23px;color:#187839; }
.ranking-row:not(.ranking-row--featured) .ranking-body { display:grid;grid-template-columns:minmax(0,1fr) auto;column-gap:12px;align-items:center; }
.ranking-row:not(.ranking-row--featured) .ranking-summary { grid-column:1;grid-row:2; }
.ranking-row:not(.ranking-row--featured) .ranking-meta { grid-column:2;grid-row:1/3; }
.ranking-row--featured { --podium:#ffd65b; --podium-ink:#ef501c; position:relative;isolation:isolate;border:1.5px solid var(--rule-strong);background:linear-gradient(135deg,color-mix(in srgb,var(--podium) 23%,var(--paper-raised)),var(--paper-raised) 60%,color-mix(in srgb,var(--podium) 25%,var(--paper-raised))); }
.ranking-row--silver { --podium:#4cbcf4; --podium-ink:#1265a8; }
.ranking-row--bronze { --podium:#ff944e; --podium-ink:#ec4d22; }
.ranking-row--featured::before { content:'';position:absolute;inset:3px;z-index:-1;pointer-events:none;background-image:radial-gradient(color-mix(in srgb,var(--podium) 78%,var(--podium-ink)) .65px,transparent .85px);background-size:3px 3px;mask-image:linear-gradient(135deg,#000,transparent 26%,transparent 76%,#000);opacity:.8; }
.ranking-row--featured::after { content:'';position:absolute;inset:3px;z-index:-1;pointer-events:none;background:linear-gradient(138deg,transparent 0 12%,color-mix(in srgb,var(--podium) 45%,transparent) 12% 13%,transparent 13% 16%,color-mix(in srgb,var(--podium) 23%,transparent) 16% 18%,transparent 18% 81%,color-mix(in srgb,var(--podium) 35%,transparent) 81% 82%,transparent 82% 89%,color-mix(in srgb,var(--podium) 48%,transparent) 89% 90%,transparent 90%);clip-path:polygon(0 0,40% 0,0 57%,0 100%,68% 100%,100% 36%,100% 100%,0 100%); }
.ranking-row--featured .ranking-link { padding:48px 13px 11px;gap:13px; }
.ranking-row--featured .ranking-number { position:absolute;left:16px;top:9px;font-size:38px;line-height:1;color:var(--podium-ink);text-shadow:1px 2px 0 var(--paper-raised); }
.ranking-row--featured .ranking-link :deep(.ranking-avatar) { width:78px;height:78px;flex-basis:78px;border:0; }
.ranking-row--featured .ranking-title { font-size:16px;letter-spacing:-.035em; }
.ranking-row--featured .ranking-summary { -webkit-line-clamp:2;font-size:13px;line-height:1.55;margin:6px 0 11px; }
.ranking-row--featured .ranking-meta { gap:17px; }
.ranking-row--featured .ranking-growth { font-size:16px; }
.ranking-row--featured .ranking-score { font-size:20px; }
.ranking-row--featured .ranking-heat { position:absolute;top:17px;right:44px; }
.ranking-row--featured .ranking-arrow { position:absolute;top:16px;right:12px;color:var(--podium-ink); }
.ranking-row--lead .ranking-score,.ranking-row--bronze .ranking-score { color:#ef481e; }
:root[data-theme='dark'] .ranking-toolbar { background:var(--paper-muted);border-color:var(--rule); }
:root[data-theme='dark'] .ranking-row--featured { border-color:var(--rule);background:linear-gradient(135deg,color-mix(in srgb,var(--podium) 5%,var(--paper-raised)),var(--paper-raised)); }
:root[data-theme='dark'] .ranking-row--featured::before { opacity:.12; }
:root[data-theme='dark'] .ranking-row--featured::after { opacity:.4; }
:root[data-theme='dark'] .ranking-row--lead { --podium-ink:#dfd397; }
:root[data-theme='dark'] .ranking-row--silver { --podium-ink:#6badcf; }
:root[data-theme='dark'] .ranking-row--bronze { --podium-ink:#ef9679; }
:root[data-theme='dark'] .ranking-number { text-shadow:none; }
:root[data-theme='dark'] .ranking-growth { color:#94ca8b; }
:root[data-theme='dark'] .ranking-arrow { color:var(--acid); }
:root[data-theme='dark'] .ranking-score { color:#bab1ed; }
:root[data-theme='dark'] .ranking-row--featured .ranking-score { color:var(--ink); }
:root[data-theme='dark'] .ranking-row--lead .ranking-score,:root[data-theme='dark'] .ranking-row--bronze .ranking-score { color:#ee8b6d; }

.ranking-row--featured { border:2px solid transparent;border-radius:6px;box-shadow:none; }
.ranking-ink-frame { position:absolute;inset:-2px;z-index:2;width:calc(100% + 4px);height:calc(100% + 4px);pointer-events:none;fill:none;stroke-linecap:round;stroke-linejoin:round; }
.ranking-ink-frame path { vector-effect:non-scaling-stroke; }
.ranking-ink-frame__outline { stroke:var(--rule-strong);stroke-width:1.8; }
.ranking-ink-frame__trace { stroke:var(--rule-strong);stroke-width:.65;opacity:.45; }
.ranking-ink-frame__strokes { stroke:var(--podium);stroke-width:1.2;opacity:.85; }
.ranking-row--silver .ranking-ink-frame { transform:scaleX(-1); }
.ranking-row--featured .ranking-number { font-weight:950;transform:skewX(-4deg); }
.ranking-toolbar { border-width:2px 2px 2.5px 2px;border-radius:8px 10px 5px 8px;box-shadow:0 1px 0 color-mix(in srgb,var(--rule-strong) 40%,transparent); }
:root[data-theme='dark'] .ranking-row--featured { border-color:transparent;box-shadow:none; }
:root[data-theme='dark'] .ranking-ink-frame__outline { stroke:var(--rule);stroke-width:1; }
:root[data-theme='dark'] .ranking-ink-frame__trace { opacity:.2; }
:root[data-theme='dark'] .ranking-ink-frame__strokes { opacity:.3; }

@media (max-width:1499px) { .ranking-tab { font-size:15px;padding-inline:12px;gap:6px; }.ranking-tab[aria-selected='true'] { font-size:19px;padding-inline:18px; }.ranking-tab-icon { width:21px;height:21px; }.ranking-live-status { font-size:11px;padding:5px 7px; }.ranking-link { gap:9px;padding-inline:9px; }.ranking-row--featured .ranking-link :deep(.ranking-avatar) { width:58px;height:58px;flex-basis:58px; }.ranking-row--featured .ranking-link { gap:9px;padding-inline:10px; }.ranking-row--featured .ranking-title { font-size:13px; }.ranking-row--featured .ranking-summary { font-size:12px; }.ranking-row--featured .ranking-score { font-size:17px; }.ranking-meta { gap:9px; }.ranking-growth,.ranking-score { font-size:12px; }.ranking-number { font-size:23px;flex-basis:30px; }.ranking-summary { font-size:11px; } }
@media (max-width:1199px) { .ranking-toolbar { flex-wrap:wrap;gap:8px;padding-bottom:5px; }.ranking-tabs { flex:1;justify-content:space-between; }.ranking-source-status { margin-left:auto; }.editorial-list { height:auto;grid-template-rows:175px repeat(7,minmax(58px,auto)); }.ranking-list { overflow:visible; }.ranking-row:not(.ranking-row--featured) .ranking-body { display:block; }.ranking-row:not(.ranking-row--featured) .ranking-meta { margin-top:3px; }.ranking-row--featured .ranking-link :deep(.ranking-avatar) { width:48px;height:48px;flex-basis:48px; } }
@media (max-width:767px) { .ranking-tabs { display:grid;grid-template-columns:repeat(3,minmax(0,1fr));width:100%; }.ranking-tab { min-height:44px;font-size:14px;padding-inline:8px; }.ranking-tab[aria-selected='true'] { font-size:17px;margin:0;transform:none;padding-inline:8px; }.ranking-tab[aria-selected='true'] > * { transform:none; }.ranking-toolbar { padding:5px; }.editorial-list { grid-template-columns:1fr;grid-template-rows:none;gap:7px; }.ranking-row--featured .ranking-link { min-height:174px; }.ranking-row:nth-child(4) { margin:0; }.ranking-link { padding-block:8px; }.ranking-title { white-space:normal;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical; }.ranking-row--featured .ranking-link :deep(.ranking-avatar) { width:76px;height:76px;flex-basis:76px; }.ranking-row--featured .ranking-title { font-size:16px; }.ranking-row--featured .ranking-summary { font-size:13px; }.ranking-row:not(.ranking-row--featured) .ranking-summary { font-size:12px; }.ranking-row:not(.ranking-row--featured) .ranking-link :deep(.ranking-avatar) { width:34px;height:34px;flex-basis:34px; }.ranking-arrow { width:17px; }.ranking-meta { flex-wrap:wrap; } }




/* One outline per tab; separators belong only between unselected tabs. */
.ranking-toolbar { border:0;border-radius:0;box-shadow:none;background:transparent; }
.ranking-tab { isolation:isolate; }
.ranking-tab[aria-selected='true'] { background:transparent;border:0;border-radius:0;transform:none;margin:0 5px 0 0;padding-inline:25px; }
.ranking-tab[aria-selected='true']::after { content:'';position:absolute;inset:0;z-index:-1;background:var(--acid);border:1.5px solid var(--rule-strong);border-radius:7px;transform:skewX(-10deg); }
.ranking-tab[aria-selected='true'] > * { transform:none; }
.ranking-tab[aria-selected='true'] + .ranking-tab::before { display:none; }
:root[data-theme='dark'] .ranking-toolbar { background:transparent; }
.ranking-row:not(.ranking-row--featured) .ranking-link { min-height:0; }
.ranking-row:not(.ranking-row--featured) .ranking-meta { display:grid;grid-template-columns:86px 82px 90px;gap:12px;align-items:center;font-variant-numeric:tabular-nums; }
.ranking-row:not(.ranking-row--featured) .ranking-growth { grid-column:1;text-align:right; }
.ranking-row:not(.ranking-row--featured) .ranking-heat { grid-column:2;justify-self:end; }
.ranking-row:not(.ranking-row--featured) .ranking-score { grid-column:3;display:grid;grid-template-columns:21px 1fr;gap:6px;text-align:right; }
@media (max-width:1499px) {
 .ranking-row:not(.ranking-row--featured) .ranking-meta { grid-template-columns:72px 75px 76px;gap:8px; }
 .ranking-tab[aria-selected='true'] { padding-inline:18px; }
}

@media (min-width:1024px) and (max-height:900px) {
  .editorial-list { grid-template-rows:110px repeat(7,minmax(36px,1fr)); }
  .editorial-list .ranking-row--featured .ranking-link { height:110px; min-height:110px; padding-top:28px; }
  .editorial-list .ranking-row--featured :deep(.ranking-avatar) { width:46px; height:46px; flex-basis:46px; }
  .editorial-list > .ranking-row:not(.ranking-row--featured) { height:39px; }
  .editorial-list .ranking-link { padding-block:3px; }
}

@media (min-width:1024px) and (max-height:760px) {
  .editorial-list { grid-template-rows:100px repeat(7,minmax(32px,1fr)); }
  .editorial-list .ranking-row--featured .ranking-link { height:100px; min-height:100px; padding-top:25px; }
  .editorial-list .ranking-row--featured :deep(.ranking-avatar) { width:42px; height:42px; flex-basis:42px; }
  .editorial-list > .ranking-row:not(.ranking-row--featured) { height:35px; }
}
</style>
