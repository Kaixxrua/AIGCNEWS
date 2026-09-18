<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useDashboardData } from '@/composables/useDashboardData'
import { useDashboardStats } from '@/composables/useDashboardStats'
import { subscribeLiveStats } from '@/composables/useLiveStatsStream'
import GlassCalendar from '@/components/GlassCalendar.vue'
import SpinnerLoader from '@/components/SpinnerLoader.vue'
import DashboardEmptyState from '@/components/dashboard/DashboardEmptyState.vue'
import DashboardOverviewPanel from '@/components/dashboard/DashboardOverviewPanel.vue'
import DigestGeometry from '@/components/dashboard/DigestGeometry.vue'
import DashboardRankingPanel from '@/components/dashboard/DashboardRankingPanel.vue'
import RollingNumber from '@/components/dashboard/RollingNumber.vue'
import { CalendarDays, ArrowRight, MailPlus, Plug, Terminal } from 'lucide-vue-next'
import type { Stats } from '@/features/dashboard/dashboardViewModel'
import { loadCatalog, type UiTemplate } from '@/features/ui-library/catalog'

defineOptions({ name: 'DashboardView' })
const { t, locale } = useI18n()
const uiCount = ref<number | null>(null)
const uiLoading = ref(true)
const uiPreview = ref<UiTemplate | null>(null)
const previewFailed = ref(false)
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
    uiPreview.value = items.find(item => item.poster_url && item.editorial) ?? items.find(item => item.poster_url) ?? null
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
        <span v-if="!loading && isViewingHistory" class="dashboard-history"><CalendarDays :size="14" />{{ currentDate }}</span>
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
        <p class="sidebar-motto">{{ t('dashboard.editorial.motto') }}</p>
        <GlassCalendar :model-value="currentDate" :available-dates="availableDates" @update:model-value="onDateChange" />
        <section class="digest-card">
          <div class="digest-heading"><MailPlus :size="27" /><h2>{{ t('dashboard.editorial.digestTitle') }}</h2></div>
          <span class="digest-edition">DAILY BRIEF <span>{{ currentDate.slice(5).replace('-', '.') }}</span></span>
          <p>{{ t('dashboard.digest.description') }}</p>
          <RouterLink :to="{ path: '/report', query: { subscribe: '1' } }" class="digest-cta">
            {{ t('dashboard.digest.cta') }}<ArrowRight :size="15" />
          </RouterLink>
          <DigestGeometry />
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
          <div class="ui-inspiration__heading"><span>{{ t('dashboard.editorial.inspiration') }}</span><ArrowRight :size="16" /></div>
          <div class="ui-inspiration__preview">
            <img v-if="uiPreview && !previewFailed" :src="uiPreview.poster_url" :alt="previewName" loading="lazy" @error="previewFailed = true" />
            <span v-else class="ui-inspiration__fallback">UI / {{ t('dashboard.editorial.explore') }}</span>
          </div>
          <div class="ui-inspiration__caption"><span>{{ previewName || t('dashboard.editorial.explore') }}</span><span>UI LIBRARY ↗</span></div>
        </RouterLink>
      </aside>
    </div>
  </div>
</template>

<style scoped>
.dashboard-page {
  --paper: #f3f2ec; --paper-light: #fffefa; --ink: #10131e; --muted: #666b70;
  --acid: #c8fc4c; --acid-soft: #f0f8d8; --rule: #e5e3dd;
  --sidebar-width: 24%; --column-gap: 14px;
  position: relative; isolation: isolate; padding: 22px 9px 18px; overflow-y: auto;
  color: var(--ink); background: transparent; font-family: Inter, "Noto Sans CJK SC", "Microsoft YaHei", sans-serif;
}
.dashboard-page::before, .dashboard-page::after { content: ''; position: absolute; z-index: -1; top: 0; bottom: 0; border: 1px solid var(--rule); border-radius: 12px; background: var(--paper); pointer-events: none; }
.dashboard-page::before { left: 0; right: calc(var(--sidebar-width) + var(--column-gap) - 1px); }
.dashboard-page::after { right: 0; width: var(--sidebar-width); }
.dashboard-heading { display: flex; align-items: center; height: 80px; gap: 20px; padding: 0 calc(var(--sidebar-width) + var(--column-gap) + 12px) 0 20px; margin-bottom: 23px; }
.dashboard-heading__copy { flex: 0 0 290px; min-width: 0; }
.dashboard-heading h1 { margin: 0 0 4px; font-size: 40px; line-height: 1.2; font-weight: 800; letter-spacing: -.035em; }
.dashboard-heading p { color: #51545b; font-size: 20px; line-height: 1.4; }
.dashboard-history { display: flex; gap: 5px; align-items: center; font-size: 12px; margin-top: 5px; }
.dashboard-heading :deep(.stat-strip) { flex: 1; }
.dashboard-main { display: grid; grid-template-columns: minmax(0, 1fr) var(--sidebar-width); gap: var(--column-gap); align-items: start; }
.dashboard-main > * { min-width: 0; }
.dashboard-sidebar { position: relative; display: flex; flex-direction: column; gap: 10px; padding: 0 0 0 1px; }
.dashboard-page :deep(.glass-card) { border: 1px solid var(--rule); border-radius: 11px; box-shadow: none; background: var(--paper-light); backdrop-filter: none; }
.sidebar-motto { position: absolute; left: 28px; bottom: calc(100% + 32px); color: #65686b; font-size: 18px; line-height: 1.45; border-left: 2px solid #9f9e97; padding-left: 22px; white-space: pre-line; }
.dashboard-sidebar :deep(.dash-calendar) { padding: 15px 20px 12px; height: 234px; border-radius: 11px; flex-shrink: 0; }
.dashboard-sidebar :deep(.dash-calendar h3) { font-family: inherit; font-size: 18px; font-weight: 750; color: var(--ink); }
.dashboard-sidebar :deep(.dash-calendar > div:first-child) { margin-bottom: 12px; }
.dashboard-sidebar :deep(.dash-calendar .calendar-day) { font-size: 14px; height: 28px; }
.dashboard-sidebar :deep(.dash-calendar .grid > span) { font-size: 14px !important; line-height: 28px !important; color: var(--muted); }
.dashboard-sidebar :deep(.calendar-day--active) { width: 30px; justify-self: center; background: var(--acid); box-shadow: none; border-radius: 7px; }
.dashboard-sidebar :deep(.snapshot-dot) { display: none; }
.dashboard-error { padding: 12px; margin-bottom: 16px; color: var(--tone-coral); border: 1px solid currentColor; border-radius: 8px; }
.digest-card { position: relative; isolation: isolate; overflow: hidden; padding: 22px 20px 18px; height: 186px; border-radius: 11px; color: #f3f5ef; background: radial-gradient(ellipse at 100% 100%, #272b26, transparent 65%), #141917; }
.digest-heading { display: flex; gap: 12px; align-items: center; }
.digest-heading > svg { color: #cefc50; flex-shrink: 0; }
.digest-heading h2 { font-size: 22px; font-weight: 750; letter-spacing: .02em; }
.digest-edition { position: absolute; right: 20px; top: 20px; display: flex; flex-direction: column; align-items: flex-end; gap: 3px; color: #c1c5bf; font-size: 10px; }
.digest-card p { position: relative; z-index: 1; max-width: 270px; font-size: 14px; line-height: 1.65; color: #c5cac4; margin: 16px 0; display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: 2; overflow: hidden; }
.digest-cta { position: absolute; bottom: 18px; left: 20px; z-index: 1; display: inline-flex; align-items: center; gap: 12px; padding: 8px 19px; border-radius: 7px; background: #cefc50; color: #12190a; font-size: 14px; line-height: 20px; font-weight: 750; }
.digest-cta:hover { background: #e0ff80; }
/* Keep the original hard-edged identity within the reference layout. */
.dashboard-page::before, .dashboard-page::after { border-color: var(--rule-strong); border-radius: 8px; }
.dashboard-page :deep(.glass-card), .dashboard-page .integration-card, .dashboard-page .ui-inspiration, .dashboard-page .digest-card {
  border: 1px solid var(--rule-strong); border-radius: 5px; box-shadow: 3px 3px 0 #171a14;
}
.dashboard-page :deep(.stat-cell) { border-color: var(--rule-strong); border-radius: 5px; box-shadow: 2px 2px 0 #171a14; }
.dashboard-page :deep(.ranking-row--featured) { border-color: var(--rule-strong) !important; border-radius: 5px; }
.dashboard-page :deep(.ranking-tabs button), .digest-cta { border: 1px solid var(--rule-strong); border-radius: 4px; }
.dashboard-sidebar :deep(.dash-calendar) { border: 1px solid var(--rule-strong); border-radius: 5px; box-shadow: 3px 3px 0 #171a14; }
.dashboard-sidebar :deep(.calendar-day--active) { border: 1px solid var(--rule-strong); border-radius: 4px; }
.integration-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.integration-card { display: flex; gap: 10px; align-items: center; height: 75px; padding: 12px 15px; border: 1px solid var(--rule); border-radius: 11px; background: var(--paper-light); }
.integration-card > svg { color: #172015; border-radius: 50%; background: #e9fcc0; padding: 7px; width: 34px; height: 34px; flex-shrink: 0; }
.integration-card > span { min-width: 0; font-size: 12px; color: #4e525a; }
.integration-card :deep(span > span), .integration-card :deep(number-flow-vue) { display: block; font-size: 24px; font-weight: 750; color: var(--ink); line-height: 1.3; }
.ui-inspiration { display: grid; grid-template-columns: 90px minmax(0, 1fr); grid-template-rows: 24px 1fr; column-gap: 14px; height: 98px; padding: 12px 15px; border: 1px solid var(--rule); border-radius: 11px; background: var(--paper-light); }
.ui-inspiration__heading { grid-column: 2; display: flex; align-items: center; justify-content: space-between; font-size: 14px; font-weight: 650; }
.ui-inspiration__preview { grid-column: 1; grid-row: 1 / 3; overflow: hidden; border-radius: 7px; background: var(--acid-soft); }
.ui-inspiration__preview img { width: 100%; height: 100%; object-fit: cover; transition: transform .3s ease; }
.ui-inspiration:hover img { transform: scale(1.04); }
.ui-inspiration__fallback { display: grid; height: 100%; place-items: center; color: var(--muted); font-size: 10px; }
.ui-inspiration__caption { display: flex; flex-direction: column; justify-content: center; gap: 5px; font-size: 12px; color: var(--muted); min-width: 0; }
.ui-inspiration__caption > span:first-child { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ui-inspiration__caption > span:last-child { font-size: 9px; letter-spacing: .1em; }
.dashboard-sidebar a:focus-visible { outline: 2px solid var(--ink); outline-offset: 3px; }
.dashboard-sidebar .digest-cta:focus-visible { outline-color: #cefc50; }
:root[data-theme='dark'] .dashboard-page { --paper: #141813; --paper-light: #1b211a; --ink: #eef2e8; --muted: #a8b0a3; --rule: #323b2f; --acid-soft: #28331c; }
:root[data-theme='dark'] .dashboard-heading p, :root[data-theme='dark'] .sidebar-motto, :root[data-theme='dark'] .integration-card > span { color: var(--muted); }
@media (max-width: 1499px) {
  .dashboard-heading__copy { flex-basis: 235px; }
  .dashboard-heading h1 { font-size: 34px; }
  .dashboard-heading p { font-size: 17px; }
  .digest-heading h2 { font-size: 18px; }
  .digest-edition { font-size: 8px; right: 12px; }
  .digest-card p { font-size: 12px; max-width: 200px; }
  .integration-card { padding: 10px; gap: 7px; }
  .integration-card > span { font-size: 10px; }
}
@media (max-width: 1199px) {
  .dashboard-page { --sidebar-width: 28%; }
  .dashboard-heading { height: auto; min-height: 125px; flex-shrink: 0; flex-wrap: wrap; gap: 14px; }
  .dashboard-heading__copy { flex-basis: 100%; }
  .dashboard-heading :deep(.stat-strip) { flex-basis: 100%; }
  .sidebar-motto { bottom: calc(100% + 65px); font-size: 16px; }
  .digest-edition { display: none; }
}
@media (max-width: 899px) {
  .dashboard-page { padding: 16px 10px; }
  .dashboard-page::before { right: 0; } .dashboard-page::after { display: none; }
  .dashboard-heading { padding: 0 10px; }
  .dashboard-main { grid-template-columns: minmax(0, 1fr); }
  .dashboard-sidebar { display: grid; grid-template-columns: 1fr 1fr; align-items: start; }
  .sidebar-motto { display: none; }
}
@media (max-width: 539px) { .dashboard-sidebar { display: flex; } }
@media (prefers-reduced-motion: reduce) { .ui-inspiration__preview img { transition: none; } }
</style>
