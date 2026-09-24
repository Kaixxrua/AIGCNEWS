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
import { ArrowRight, Mail, Plug, Terminal, Check } from 'lucide-vue-next'
import type { Stats } from '@/features/dashboard/dashboardViewModel'
import { loadCatalog, type UiTemplate } from '@/features/ui-library/catalog'

defineOptions({ name: 'DesktopDashboardView' })
const { t, locale } = useI18n()
const digestFeatures = ['featureSchedule', 'featureEmailRss', 'featureChat', 'featureWebhook'] as const
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
  errorMsg,
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
  <div class="dashboard-page">
    <header class="dashboard-heading">
      <div class="dashboard-heading__copy">
        <h1>{{ t('dashboard.editorial.title') }}</h1>
        <p>{{ t('dashboard.editorial.subtitle') }}</p>
      </div>
      <DashboardOverviewPanel v-if="!loading" :loading="loading" :active-tab="activeTab"
        :stat-values="statValues" :visitor-values="visitorValues" :ui-count="uiCount" :ui-loading="uiLoading"
        @select-source="selectSourceTab" />
    </header>
    <div v-if="errorMsg" class="dashboard-error" role="alert">{{ errorMsg }}</div>
    <div class="dashboard-main">
      <SpinnerLoader v-if="loading" class="min-h-[360px]" />
      <DashboardEmptyState v-else-if="isEmbargoed" variant="embargoed" />
      <DashboardEmptyState v-else-if="!hasData && !tabLoading" variant="no-data" />
      <DashboardRankingPanel v-else :active-tab="activeTab" :tab-list="tabList" :tab-loading="tabLoading"
        :is-viewing-history="isViewingHistory" :is-finalized="isFinalized" :source-status="sourceStatus"
        @select-source="selectSourceTab" />

      <aside v-if="!loading" class="dashboard-sidebar min-h-0">
        <GlassCalendar :model-value="currentDate" :today-date="todayStr" :available-dates="availableDates" @update:model-value="onDateChange" />
        <section class="digest-card">
          <svg class="digest-ink-frame" viewBox="0 0 400 230" preserveAspectRatio="none" aria-hidden="true"><path d="M10 3 Q5 2 4 12 L3 216 Q2 225 13 226 L387 228 Q396 227 396 216 L398 14 Q399 5 388 4 Z" /></svg>
          <div class="digest-heading"><span class="digest-mail"><Mail :size="30" :stroke-width="2.8" /></span><h2>{{ t('dashboard.editorial.digestTitle') }}</h2></div>
          <p>{{ t('dashboard.editorial.digestDescription') }}</p>
          <ul class="digest-features"><li v-for="feature in digestFeatures" :key="feature"><Check :size="16" aria-hidden="true" />{{ t(`dashboard.digest.${feature}`) }}</li></ul>
          <RouterLink :to="{ path: '/report', query: { subscribe: '1' } }" class="digest-cta">
            {{ t('dashboard.digest.cta') }}<ArrowRight :size="15" />
          </RouterLink>
          <img class="digest-robot" src="/assets/comic/digest-robot-integrated.webp" alt="" aria-hidden="true" />
        </section>
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
.dashboard-page { --sidebar-width:24%;display:grid;grid-template-columns:minmax(0,1fr) var(--sidebar-width);grid-template-rows:74px minmax(0,1fr);gap:14px 24px;position:relative;isolation:isolate;height:100%;min-height:0;padding:16px 12px 6px;color:var(--ink); }
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
.dashboard-sidebar { grid-column:2;grid-row:1/3;display:grid;grid-template-rows:214px minmax(180px,226px) 66px minmax(81px,1fr);align-content:start;gap:12px;min-width:0;min-height:0; }
.dashboard-sidebar a:focus-visible { outline:2px solid var(--ink);outline-offset:3px; }
.dashboard-error { position:absolute;top:0;left:12px;right:12px;z-index:3;padding:8px;color:var(--ink);background:var(--paper-raised);border:1px solid var(--tone-coral);border-radius:5px; }

.dashboard-sidebar :deep(.dash-calendar) { padding:8px 12px;border:solid var(--rule-strong);border-width:2px 2.5px 2px 2px;border-radius:5px 9px 4px 6px;background:var(--paper);box-shadow:inset -2px -2px 0 color-mix(in srgb,var(--rule-strong) 12%,transparent); }
.dashboard-sidebar :deep(.dash-calendar h3) { color:var(--ink);font-family:inherit;font-size:24px;font-weight:850; }
.dashboard-sidebar :deep(.dash-calendar > div:first-child) { margin-bottom:4px; }
.dashboard-sidebar :deep(.dash-calendar > .grid:last-child) { flex:1;min-height:0;grid-auto-rows:minmax(0,1fr); }
.dashboard-sidebar :deep(.dash-calendar .calendar-day) { height:100%;min-height:20px;font-size:15px;color:var(--ink); }
.dashboard-sidebar :deep(.dash-calendar .calendar-day.text-stone-300) { color:var(--muted); }
.dashboard-sidebar :deep(.dash-calendar .calendar-day--disabled) { opacity:.65; }
.dashboard-sidebar :deep(.dash-calendar .grid > span) { font-size:14px !important;line-height:25px !important;color:var(--ink-secondary); }
.dashboard-sidebar :deep(.calendar-day--active) { width:39px;justify-self:center;font-size:20px !important;font-weight:850;border:1.5px solid var(--rule-strong);border-radius:4px;box-shadow:none !important; }
.dashboard-sidebar :deep(.calendar-day--active)::before { content:'';position:absolute;inset:-13px;z-index:0;pointer-events:none;background:repeating-conic-gradient(from 5deg,var(--acid) 0 3deg,transparent 3deg 32deg);mask:radial-gradient(ellipse,transparent 56%,#000 59%); }
.dashboard-sidebar :deep(.cal-nav) { color:var(--ink);width:35px; }
.dashboard-sidebar :deep(.cal-nav svg) { width:19px;height:19px; }
.dashboard-sidebar :deep(.snapshot-dot) { display:none; }

/* Copy keeps its own rhythm; the illustration sits behind the ink frame, never the text. */
.digest-card { position:relative;isolation:isolate;overflow:visible;display:flex;flex-direction:column;container-type:inline-size;padding:12px 14px;border:solid transparent;border-width:2px 2.5px 3px 2px;border-radius:6px 8px 5px 9px;background:var(--paper);box-shadow:none; }
.digest-card::before { content:'';position:absolute;inset:0;z-index:-1;border-radius:inherit;background-image:linear-gradient(135deg,transparent 0 67%,var(--comic-cyan-line) 67% 70%,transparent 70% 73%,color-mix(in srgb,var(--comic-cyan-line) 33%,transparent) 73% 74%,transparent 74%),radial-gradient(var(--comic-cyan-dot) .6px,transparent .8px);background-size:100% 100%,3px 3px;mask-image:linear-gradient(120deg,transparent 43%,#000 90%);opacity:.38; }
.digest-ink-frame { position:absolute;inset:-2px;width:calc(100% + 4px);height:calc(100% + 4px);fill:none;stroke:var(--rule-strong);stroke-width:2.4;pointer-events:none;z-index:1; }
.digest-ink-frame path { vector-effect:non-scaling-stroke; }
.digest-heading { position:relative;z-index:1;display:flex;flex:none;align-items:center;gap:11px;margin-bottom:4px; }
.digest-mail { display:grid;place-items:center;position:relative;width:37px;height:34px;flex-shrink:0;transform:rotate(-6deg);background:var(--comic-cyan);color:var(--ink);border-radius:3px 6px 2px 4px;box-shadow:2px 1px 0 color-mix(in srgb,var(--comic-cyan-line) 40%,transparent); }
.digest-mail svg { width:31px;height:29px;filter:drop-shadow(1px 1px 0 var(--paper)); }
.digest-heading h2 { font-size:25px;line-height:1.3;font-weight:950;letter-spacing:-.025em; }
.digest-card p { position:relative;z-index:4;max-width:58%;margin:0 0 6px;color:var(--ink-secondary);font-size:12px;line-height:1.45;text-wrap:pretty; }
.digest-features { position:relative;z-index:4;display:flex;flex-direction:column;gap:2px;max-width:48%;font-size:15px;line-height:18px;font-weight:750; }
.digest-features li { display:flex;align-items:center;gap:10px;min-height:19px; }
.digest-features svg { flex-shrink:0;background:var(--comic-cyan);color:var(--ink);border-radius:50%;padding:2px;width:19px;height:19px;stroke-width:3; }
.digest-cta { position:relative;z-index:4;display:flex;flex:none;align-items:center;justify-content:center;gap:13px;width:48%;height:36px;margin-top:auto;border:solid var(--rule-strong);border-width:2px 3px 3px 2px;border-radius:12px 9px 13px 8px;background:var(--acid);color:var(--acid-ink);font-size:17px;font-weight:850; }
.digest-cta svg { width:23px;height:23px; }
.digest-robot { position:absolute;z-index:2;right:-14px;bottom:0;width:56%;height:106%;object-fit:contain;object-position:right bottom;pointer-events:none; }
@container (max-width:419px) {
  .digest-card p { max-width:62%;font-size:11px; }
  .digest-features { max-width:52%;font-size:13px;line-height:16px; }
  .digest-features li { gap:7px;min-height:17px; }
  .digest-features svg { width:16px;height:16px; }
  .digest-cta { width:52%;height:32px;font-size:15px; }
  .digest-robot { width:52%; }
}
@container (max-width:359px) {
  .digest-card p { max-width:66%; }
  .digest-features { max-width:56%;font-size:12px;line-height:15px; }
  .digest-cta { width:56%; }
  .digest-robot { width:49%; }
}

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
:root[data-theme='dark'] .digest-card { border-width:1px;background:var(--paper-raised); }
:root[data-theme='dark'] .digest-card::before { opacity:.12; }
:root[data-theme='dark'] .digest-ink-frame { stroke-width:1; }
:root[data-theme='dark'] .digest-mail { box-shadow:none; }
:root[data-theme='dark'] .digest-mail svg { filter:none; }
:root[data-theme='dark'] .digest-robot { filter:saturate(.64) brightness(.77); }
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
  .dashboard-page { grid-template-columns:minmax(0,1fr) 29%;grid-template-rows:auto auto;align-content:start;overflow:hidden auto;overscroll-behavior:contain;scrollbar-width:thin;scrollbar-color:var(--rule) transparent;padding-top:15px;gap:14px; }
  .dashboard-heading { flex-wrap:wrap; }
  .dashboard-heading__copy { flex-basis:100%; }
  .dashboard-heading h1 { font-size:34px;line-height:1.2;margin-bottom:5px;letter-spacing:-.045em; }
  .dashboard-heading p { font-size:16px;line-height:1.4; }
  .dashboard-heading :deep(.stat-strip) { flex-basis:100%;height:auto; }
  .dashboard-sidebar { grid-template-rows:214px auto 66px minmax(81px,1fr); }
  .dashboard-sidebar :deep(.dash-calendar .calendar-day) { height:28px; }
  .digest-cta { margin-top:10px; }
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
  .dashboard-heading :deep(.stat-cell) { min-height:64px;padding-block:5px; }
  .dashboard-sidebar { gap:9px;grid-template-rows:187px 170px 58px minmax(62px,1fr); }
  .dashboard-sidebar :deep(.dash-calendar .calendar-day) { min-height:19px; }
  .digest-card { min-height:0;padding:9px 11px; }
  .digest-heading { margin-bottom:2px; }
  .digest-mail { width:30px;height:28px; }
  .digest-mail svg { width:27px;height:25px; }
  .digest-heading h2 { font-size:21px; }
  .digest-card p { max-width:80%;margin-bottom:4px;font-size:10px;line-height:1.3; }
  .digest-features { gap:1px;font-size:11px;line-height:13px; }
  .digest-features li { min-height:14px; }
  .digest-features svg { width:15px;height:15px; }
  .digest-cta { height:27px;font-size:14px; }
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
</style>
