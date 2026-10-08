<script setup lang="ts">
import { computed, onActivated, onBeforeUnmount, onDeactivated, onMounted, ref } from 'vue'
import { useDocumentVisibility, useElementVisibility, usePreferredReducedMotion } from '@vueuse/core'
import { useI18n } from 'vue-i18n'
import { useDashboardData } from '@/composables/useDashboardData'
import { useDashboardStats } from '@/composables/useDashboardStats'
import { subscribeLiveStats } from '@/composables/useLiveStatsStream'
import GlassCalendar from '@/components/GlassCalendar.vue'
import SpinnerLoader from '@/components/SpinnerLoader.vue'
import DashboardEmptyState from '@/components/dashboard/DashboardEmptyState.vue'
import DashboardOverviewPanel from '@/components/dashboard/DashboardOverviewPanel.vue'
import DashboardRankingPanel from '@/components/dashboard/DashboardRankingPanel.vue'
import RollingNumber from '@/components/dashboard/RollingNumber.vue'
import DashboardNewWords from '@/components/dashboard/DashboardNewWords.vue'
import DashboardDigestCard from '@/components/dashboard/DashboardDigestCard.vue'
import { ArrowRight, Plug, Terminal } from 'lucide-vue-next'
import type { Stats } from '@/features/dashboard/dashboardViewModel'
import { loadCatalog, type UiTemplate } from '@/features/ui-library/catalog'

defineOptions({ name: 'DashboardContent' })
const { t, locale } = useI18n()
const uiCount = ref<number | null>(null)
const uiLoading = ref(true)
const uiPreview = ref<UiTemplate | null>(null)
const previewFailed = ref(false)
const clipFailed = ref(false)
const previewElement = ref<HTMLElement>()
const previewVisible = useElementVisibility(previewElement)
const active = ref(true)
onActivated(() => { active.value = true })
onDeactivated(() => { active.value = false })
const visibility = useDocumentVisibility()
const motion = usePreferredReducedMotion()
const previewName = computed(() => uiPreview.value?.name[locale.value.startsWith('zh') ? 'zh' : 'en'] ?? '')
const uiCatalogController = new AbortController()
let currentStats: () => Stats = () => ({})
const {
  statValues,
  visitorValues,
  mcpTotalCalls,
  mcpDshCalls,
  updateStatSources,
  updateVisitorSources,
} = useDashboardStats(() => currentStats())

const {
  activeTab,
  tabList,
  stats,
  loading,
  tabLoading,
  loadError,
  retrying,
  retry,
  currentDate,
  todayStr,
  availableDates,
  isViewingHistory,
  isFinalized,
  isEmbargoed,
  sourceStatus,
  selectSourceTab,
  onDateChange,
  hasData,
  applyLiveStats,
} = useDashboardData({
  updateStatSources,
  updateVisitorSources,
})
currentStats = () => stats.value

// 与顶栏共用 SSE；断流后的轮询由共享订阅统一管理。
subscribeLiveStats(applyLiveStats)

onMounted(async () => {
  try {
    const items = await loadCatalog(uiCatalogController.signal)
    uiCount.value = items.length
    const clips = items.filter(item => item.clip_url && item.poster_url)
    const candidates = clips.length ? clips : items.filter(item => item.poster_url)
    uiPreview.value = candidates[Math.floor(Math.random() * candidates.length)] ?? null
  } catch {
    // 目录不可用时显示未知，不把加载失败误报为零。
  } finally {
    uiLoading.value = false
  }
})

onBeforeUnmount(() => uiCatalogController.abort())

</script>

<template>
  <div class="dashboard-page" :class="{ 'dashboard-page--notice': loadError && tabList.length }">
    <header class="dashboard-heading">
      <div class="dashboard-heading__copy">
        <h1>{{ t('dashboard.editorial.title') }}</h1>
        <p>{{ t('dashboard.editorial.subtitle') }}</p>
      </div>
      <DashboardOverviewPanel :loading="loading" :active-tab="activeTab"
        :stat-values="statValues" :visitor-values="visitorValues" :ui-count="uiCount" :ui-loading="uiLoading"
        @select-source="selectSourceTab" />
    </header>
    <!-- 后台刷新失败但还有上次的榜单：保留榜单，顶部说明并给重试；一条都没有时见下方失败状态 -->
    <div v-if="loadError && tabList.length" class="dashboard-error" role="alert">
      <span>{{ t('dashboard.loadError.stale') }}</span>
      <button type="button" class="btn-secondary px-3 py-1 text-xs" :disabled="retrying" :aria-busy="retrying ? 'true' : undefined" @click="retry">{{ retrying ? t('common.loading') : t('common.retry') }}</button>
    </div>
    <div class="dashboard-main">
      <SpinnerLoader v-if="loading" class="min-h-[360px]" />
      <DashboardEmptyState v-else-if="loadError && !tabList.length && !tabLoading" variant="error" :error="loadError" :retrying="retrying" @retry="retry" />
      <DashboardEmptyState v-else-if="isEmbargoed" variant="embargoed" />
      <DashboardEmptyState v-else-if="!hasData && !tabLoading" variant="no-data" />
      <DashboardRankingPanel v-else :active-tab="activeTab" :tab-list="tabList" :tab-loading="tabLoading"
        :is-viewing-history="isViewingHistory" :is-finalized="isFinalized" :source-status="sourceStatus"
        @select-source="selectSourceTab" />

      <aside v-if="!loading" class="dashboard-sidebar min-h-0">
        <GlassCalendar :model-value="currentDate" :today-date="todayStr" :available-dates="availableDates" @update:model-value="onDateChange" />
        <DashboardNewWords :date="currentDate" :historical="isViewingHistory" />
        <DashboardDigestCard />
        <div class="integration-grid">
          <RouterLink to="/mcp" class="integration-card integration-card--mcp" :aria-label="t('dashboard.mcpCalls.title')">
            <Plug :size="19" /><span>{{ t('dashboard.mcpCalls.title') }}<RollingNumber :value="mcpTotalCalls" grouping /></span>
          </RouterLink>
          <RouterLink to="/dsh" class="integration-card integration-card--dsh items-center" :aria-label="t('dashboard.dshCalls.title')">
            <Terminal :size="19" /><span>{{ t('dashboard.dshCalls.title') }}<RollingNumber :value="mcpDshCalls" grouping /></span>
          </RouterLink>
        </div>
        <RouterLink :to="uiPreview ? { name: 'ui-library', params: { id: uiPreview.id } } : { name: 'ui-library' }" class="ui-inspiration">
          <div class="ui-inspiration__body">
            <div class="ui-inspiration__heading"><span>{{ t('dashboard.editorial.inspiration') }}</span><ArrowRight :size="16" /></div>
            <div ref="previewElement" class="ui-inspiration__preview">
              <video v-if="uiPreview?.clip_url && !clipFailed && active && previewVisible && motion !== 'reduce' && visibility === 'visible'" :src="uiPreview.clip_url" :poster="uiPreview.poster_url" :aria-label="previewName" autoplay muted loop playsinline @error="clipFailed = true" />
              <img v-else-if="uiPreview && !previewFailed" :src="uiPreview.poster_url" :alt="previewName" loading="lazy" @error="previewFailed = true" />
              <span v-else class="ui-inspiration__fallback">UI / {{ t('dashboard.editorial.explore') }}</span>
            </div>
            <div class="ui-inspiration__caption"><span>{{ previewName || t('dashboard.editorial.explore') }}</span><span>UI LIBRARY ↗</span></div>
          </div>
        </RouterLink>
      </aside>
    </div>
  </div>
</template>

<style scoped>
.dashboard-page { --sidebar-width:24%;display:grid;grid-template-columns:minmax(0,1fr) var(--sidebar-width);grid-template-rows:74px minmax(0,1fr);gap:14px 24px;position:relative;isolation:isolate;height:100%;min-height:0;padding:16px 12px 20px;color:var(--ink); }
.dashboard-heading { grid-column:1;grid-row:1;display:flex;align-items:center;min-width:0;gap:16px; }
.dashboard-heading__copy { flex:0 0 auto;min-width:0;padding:0 30px 0 5px; }
.dashboard-heading h1 { text-shadow:1px 1px 0 var(--paper-raised);position:relative;isolation:isolate;display:inline-block;margin:0 0 4px;font-size:35px;font-style:italic;font-weight:950;line-height:1.1;letter-spacing:0;white-space:nowrap; }
/* Marker stroke under the lower third of the title and a spark sticker off its corner; the glyphs stay on top. */
.dashboard-heading h1::before { content:'';position:absolute;z-index:-1;inset:70% -4px 1px;background:var(--acid);transform:rotate(-5deg) skewX(-18deg); }
.dashboard-heading h1::after { content:'';position:absolute;right:-36px;top:-15px;width:24px;height:28px;background:var(--acid);clip-path:polygon(0 0,15% 0,12% 65%,0 65%,60% 10%,80% 20%,22% 85%,15% 78%,95% 66%,100% 82%,25% 100%,23% 88%); }
.dashboard-heading p { font-size:16px;font-weight:700;line-height:1.25;white-space:nowrap; }
.dashboard-heading :deep(.stat-strip) { flex:1;height:100%; }
.dashboard-main { display:contents; }
.dashboard-main > :not(aside) { grid-column:1;grid-row:2;min-width:0; }
.dashboard-sidebar { grid-column:2;grid-row:1/3;display:grid;grid-template-rows:214px max-content max-content 66px minmax(81px,1fr);align-content:start;gap:12px;min-width:0;min-height:0;overflow-y:auto;padding:0 3px 4px 0; }
.dashboard-sidebar a:focus-visible { outline:2px solid var(--ink);outline-offset:3px; }
/* 刷新失败的提示单占一行：榜单整体下移、列表在自己的滚动区里变短，不再盖住标题、统计和日历。 */
.dashboard-error { grid-column:1;grid-row:2;display:flex;align-items:center;justify-content:space-between;gap:12px;min-width:0;padding:6px 8px 6px 12px;font-size:14px;color:var(--ink);background:var(--paper-raised);border:1px solid var(--tone-coral);border-radius:5px; }
.dashboard-page--notice { grid-template-rows:74px auto minmax(0,1fr); }
.dashboard-page--notice .dashboard-main > :not(aside) { grid-row:3; }
.dashboard-page--notice .dashboard-sidebar { grid-row:1/4; }

.dashboard-sidebar :deep(.dash-calendar) { padding:8px 12px;border:solid var(--rule-strong);border-width:2px 2.5px 2px 2px;border-radius:5px 9px 4px 6px;background:var(--paper);box-shadow:inset -2px -2px 0 color-mix(in srgb,var(--rule-strong) 12%,transparent); }
.dashboard-sidebar :deep(.dash-calendar h3) { color:var(--ink);font-family:inherit;font-size:24px;font-weight:850; }
.dashboard-sidebar :deep(.dash-calendar > div:first-child) { margin-bottom:4px; }
.dashboard-sidebar :deep(.dash-calendar > .grid:last-child) { flex:1;min-height:0;grid-auto-rows:minmax(0,1fr); }
.dashboard-sidebar :deep(.dash-calendar .calendar-day) { height:100%;min-height:20px;font-size:15px;color:var(--ink); }
.dashboard-sidebar :deep(.dash-calendar .calendar-day.text-stone-300) { color:var(--muted); }
.dashboard-sidebar :deep(.dash-calendar .calendar-day--disabled) { opacity:.65; }
.dashboard-sidebar :deep(.dash-calendar .grid > span) { font-size:14px !important;line-height:25px !important;color:var(--ink-secondary); }
.dashboard-sidebar :deep(.calendar-day--active) { width:39px;justify-self:center;font-size:20px !important;font-weight:850;border:1.5px solid var(--rule-strong);border-radius:4px;box-shadow:none !important; }
.dashboard-sidebar :deep(.calendar-day--active)::before { content:'';position:absolute;inset:-13px;z-index:0;pointer-events:none;background:repeating-conic-gradient(from 5deg,var(--acid) 0 3deg,transparent 3deg 32deg);mask:radial-gradient(ellipse,transparent 56%,#000 59%);animation:motion-burst 560ms var(--motion-pop) both; }
/* 选中日期的底块由 v-indicator 画在日期网格上滑到新日期；墨框随底块走，光芒在新日期上炸开。 */
.dashboard-sidebar :deep(.calendar-days)::before { border:1.5px solid var(--rule-strong);box-shadow:none; }
.dashboard-sidebar :deep(.calendar-days[data-indicator] .calendar-day--active) { border-color:transparent; }
@media (prefers-reduced-motion:reduce) { .dashboard-sidebar :deep(.calendar-day--active)::before { animation:none; } }
.dashboard-sidebar :deep(.cal-nav) { color:var(--ink);width:35px; }
.dashboard-sidebar :deep(.cal-nav svg) { width:19px;height:19px; }
.dashboard-sidebar :deep(.snapshot-dot) { display:none; }

.integration-grid { display:grid;container-type:inline-size;grid-template-columns:1fr 1fr;gap:10px; }
.integration-card { height:100%;min-height:0;overflow:hidden;display:flex;align-items:center;gap:10px;min-width:0;padding:10px 12px;border:1.5px solid var(--rule-strong);border-radius:8px 5px 7px 6px;background:var(--paper); }
.integration-card > svg { width:40px;height:40px;padding:8px;flex-shrink:0;border-radius:10px;background:color-mix(in srgb,var(--integration-mcp) 22%,var(--paper-raised));color:var(--ink); }
.integration-card--dsh > svg { background:color-mix(in srgb,var(--integration-dsh) 25%,var(--paper-raised));color:var(--integration-dsh-ink); }
.integration-card > span { display:flex;flex-direction:column;gap:3px;min-width:0;font-size:12px;line-height:1.25;color:var(--ink-secondary); }
.integration-card :deep(number-flow-vue),.integration-card :deep(span > span) { display:block;color:var(--ink);font-size:24px;line-height:1.05;font-weight:850; }
.ui-inspiration { display:block;container-type:size;min-height:0;padding:8px;border:1.5px solid var(--rule-strong);border-radius:7px;background:var(--paper); }
.ui-inspiration__body { display:grid;height:100%;grid-template-columns:min(45%,133cqh) minmax(0,1fr);grid-template-rows:25px 1fr;column-gap:10px; }
.ui-inspiration__heading { grid-column:2;display:flex;align-items:center;justify-content:space-between;font-size:20px;font-weight:850; }
.ui-inspiration__heading svg { width:23px;height:23px; }
.ui-inspiration__preview { grid-column:1;grid-row:1/3;overflow:hidden;border:1px solid var(--rule);border-radius:6px;background:var(--paper-muted); }
.ui-inspiration__preview video,.ui-inspiration__preview img { width:100%;height:100%;object-fit:cover; }
.ui-inspiration__fallback { display:grid;height:100%;place-items:center;font-size:11px;color:var(--muted); }
.ui-inspiration__caption { display:flex;flex-direction:column;justify-content:center;gap:2px;min-width:0;color:var(--ink-secondary);font-size:13px;line-height:1.25; }
.ui-inspiration__caption > span:first-child { overflow:hidden;text-overflow:ellipsis;white-space:nowrap; }
.ui-inspiration__caption > span:last-child { color:var(--ink);font-size:12px; }

:root[data-theme='dark'] .dashboard-heading h1 { color:var(--acid); }
:root[data-theme='dark'] .dashboard-heading h1::before { opacity:0; }
:root[data-theme='dark'] .dashboard-sidebar :deep(.dash-calendar) { border-width:1px;background:var(--paper-raised); }
:root[data-theme='dark'] .integration-card,:root[data-theme='dark'] .ui-inspiration { background:var(--paper-raised); }

@media (max-width:1499px) {
  .dashboard-page { gap:12px 20px; }
  .dashboard-heading { gap:12px; }
  .dashboard-heading h1 { font-size:30px; }
  .dashboard-heading p { font-size:14px; }
  .integration-card { gap:8px;padding-inline:10px; }
  .integration-card > svg { width:34px;height:34px;padding:6px; }
  .integration-card > span { font-size:11px; }
  .integration-card :deep(number-flow-vue),.integration-card :deep(span > span) { font-size:21px; }
}
@media (max-width:1199px) {
  /* The stacked layout outgrows the viewport; scroll inside the canvas so nothing slips under the dock. */
  .dashboard-page { grid-template-columns:minmax(0,1fr) 29%;grid-template-rows:auto auto;align-content:start;overflow:hidden auto;overscroll-behavior:contain;padding-top:15px;gap:14px; }
  .dashboard-page--notice { grid-template-rows:auto auto auto; }
  .dashboard-heading { flex-wrap:wrap; }
  .dashboard-heading__copy { flex-basis:100%; }
  .dashboard-heading h1 { font-size:34px;line-height:1.2;margin-bottom:5px;letter-spacing:-.045em; }
  .dashboard-heading p { font-size:16px;line-height:1.4; }
  .dashboard-heading :deep(.stat-strip) { flex-basis:100%;height:auto; }
  .dashboard-sidebar { grid-template-rows:214px max-content max-content 66px minmax(81px,1fr); }
  .dashboard-sidebar :deep(.dash-calendar .calendar-day) { height:28px; }
  .integration-card > svg { width:30px;height:30px;padding:5px; }
  .integration-card :deep(number-flow-vue),.integration-card :deep(span > span) { font-size:19px; }
  .ui-inspiration__body { grid-template-columns:55px minmax(0,1fr); }
  .ui-inspiration__heading { font-size:17px; }
}
@media (min-width:1200px) {
  .dashboard-heading :deep(.stat-cell) { min-height:74px;padding-block:8px; }
}
@media (min-width:1200px) and (max-height:820px) {
  .dashboard-page { grid-template-rows:64px minmax(0,1fr);padding-top:10px; }
  .dashboard-page--notice { grid-template-rows:64px auto minmax(0,1fr); }
  .dashboard-heading :deep(.stat-cell) { min-height:64px;padding-block:5px; }
  .dashboard-sidebar { gap:9px;grid-template-rows:187px max-content max-content 58px minmax(62px,1fr); }
  .dashboard-sidebar :deep(.dash-calendar .calendar-day) { min-height:19px; }
  .integration-card { padding-block:7px; }
  .integration-card :deep(number-flow-vue),.integration-card :deep(span > span) { font-size:20px; }
  .ui-inspiration__body { grid-template-rows:20px 1fr; }
  .ui-inspiration__heading { font-size:17px; }
  .ui-inspiration__caption { font-size:11px; }
}
/* Narrow cards: a small icon leads the label and the count takes its own line, so neither wraps. */
@container (max-width:319px) {
  .integration-card { display:grid;grid-template-columns:auto minmax(0,1fr);align-content:center;align-items:center;gap:3px 6px; }
  .integration-card > svg { width:20px;height:20px;padding:3px;border-radius:6px; }
  .integration-card > span { display:contents; }
  .integration-card :deep(number-flow-vue),.integration-card :deep(span > span) { grid-column:1 / -1; }
}
/* Tall card: the preview spans the full width instead of shrinking to a thumbnail. */
@container (min-height:170px) {
  .ui-inspiration__body { grid-template-columns:minmax(0,1fr);grid-template-rows:25px minmax(0,1fr) auto;row-gap:8px; }
  .ui-inspiration__heading,.ui-inspiration__preview,.ui-inspiration__caption { grid-column:1; }
  .ui-inspiration__preview { grid-row:2; }
  .ui-inspiration__caption { flex-direction:row;justify-content:space-between;align-items:baseline;gap:12px; }
  .ui-inspiration__caption > span:last-child { flex-shrink:0; }
}
/* Keep the desktop cards and content order in one flowing, touch-friendly page. */
@media (max-width:1023px) {
  .dashboard-page { display:flex;flex-direction:column;height:auto;overflow:visible;gap:20px;padding:22px 8px 28px; }
  .dashboard-heading { flex-direction:column;align-items:stretch;gap:18px; }
  .dashboard-heading__copy { flex-basis:auto;padding:0 30px 0 2px; }
  .dashboard-heading h1 { font-size:30px;letter-spacing:0; }
  .dashboard-heading p { margin-top:6px;font-size:14px;white-space:normal; }
  .dashboard-heading :deep(.stat-strip) { flex:0 0 auto; }
  .dashboard-main { display:flex;flex-direction:column;gap:24px; }
  .dashboard-sidebar { grid-template-columns:repeat(2,minmax(0,1fr));grid-template-rows:auto auto;gap:16px; }
  .dashboard-sidebar { overflow:visible;padding:0; }
  .dashboard-sidebar :deep(.dash-calendar) { grid-row:span 2;padding:14px; }
  .dashboard-sidebar :deep(.dash-calendar .calendar-day) { height:40px;min-height:40px; }
  .dashboard-sidebar :deep(.cal-nav) { width:44px;height:44px; }
  .dashboard-sidebar :deep(.dash-calendar > .grid:last-child) { flex:none; }
  .integration-grid { min-height:88px; }
  .ui-inspiration { min-height:110px;container-type:inline-size; }
  .ui-inspiration__body { grid-template-columns:100px minmax(0,1fr); }
  .dashboard-error { align-items:flex-start;flex-wrap:wrap; }
  .dashboard-error button { min-height:44px; }
}
@media (max-width:599px) {
  .dashboard-sidebar { grid-template-columns:minmax(0,1fr);grid-template-rows:auto; }
  .dashboard-sidebar :deep(.dash-calendar) { grid-row:auto; }
  .dashboard-heading h1 { font-size:28px; }
  .dashboard-sidebar :deep(.dash-calendar .calendar-day) { height:44px;min-height:44px; }
}
</style>
