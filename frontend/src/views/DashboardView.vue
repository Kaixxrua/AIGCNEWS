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
        <span class="dashboard-eyebrow">THE DAILY SIGNAL</span>
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
          <div class="digest-heading"><MailPlus :size="23" /><h2>{{ t('dashboard.digest.title') }}</h2></div>
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
  --paper: var(--projects-paper); --paper-light: var(--projects-paper-light);
  --ink: var(--projects-accent); --acid: var(--projects-acid); --acid-soft: var(--projects-acid-soft);
  --muted: var(--dash-muted);
  padding: 20px 24px 24px; overflow-y: auto; color: var(--ink);
  background: var(--paper); font-family: Inter, ui-sans-serif, system-ui, sans-serif;
}
.dashboard-heading { display: flex; align-items: center; gap: 28px; margin-bottom: 18px; }
.dashboard-heading__copy { flex: 1; min-width: 230px; }
.dashboard-eyebrow { font-size: 9px; letter-spacing: .22em; color: var(--muted); font-weight: 700; }
.dashboard-heading h1 { margin: 5px 0 4px; font-size: clamp(26px, 2.4vw, 36px); line-height: 1.2; font-weight: 850; letter-spacing: -.045em; }
.dashboard-heading p { color: var(--muted); font-size: 14px; }
.dashboard-history { display: flex; gap: 5px; align-items: center; font-size: 12px; margin-top: 6px; }
.dashboard-heading :deep(.stat-strip) { flex: 0 1 780px; }
.dashboard-main { display: grid; grid-template-columns: minmax(0, 1fr) 300px; gap: 16px; align-items: start; }
.dashboard-main > * { min-width: 0; }
.dashboard-sidebar { display: flex; flex-direction: column; gap: 12px; }
.dashboard-page :deep(.glass-card) { border: 1px solid var(--rule); border-radius: 12px; box-shadow: none; background: var(--paper-light); backdrop-filter: none; }
.sidebar-motto { display: none; color: var(--muted); font-size: 15px; border-left: 2px solid var(--rule-strong); padding-left: 16px; white-space: pre-line; }
.dashboard-error { padding: 12px; margin-bottom: 16px; color: var(--tone-coral); border: 1px solid currentColor; border-radius: 8px; }
.digest-card { position: relative; isolation: isolate; overflow: hidden; padding: 18px; border-radius: 12px; color: #f4f5ed; background: radial-gradient(ellipse at 100% 100%, #303c2c, transparent 70%), #131916; min-height: 180px; }
.digest-heading { display: flex; gap: 10px; align-items: center; }
.digest-heading > svg { color: #d6fb53; flex-shrink: 0; }
.digest-heading h2 { font-size: 17px; font-weight: 750; letter-spacing: -.04em; }
.digest-edition { display: flex; gap: 8px; margin: 10px 0; color: #abb5a7; font-size: 9px; letter-spacing: .14em; }
.digest-card p { position: relative; z-index: 1; max-width: 205px; font-size: 12px; line-height: 1.8; color: #ccd3c8; margin-bottom: 16px; }
.digest-cta { position: relative; z-index: 1; display: inline-flex; align-items: center; gap: 12px; padding: 8px 14px; border-radius: 7px; background: #d6fb53; color: #15200c; font-size: 12px; font-weight: 750; }
.digest-cta:hover { background: #e4ff88; }
.integration-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.integration-card { display: flex; gap: 9px; align-items: center; padding: 13px 10px; border: 1px solid var(--rule); border-radius: 10px; background: var(--paper-light); }
.integration-card > svg { color: var(--ink); border-radius: 50%; background: var(--acid-soft); padding: 6px; width: 32px; height: 32px; flex-shrink: 0; }
.integration-card > span { min-width: 0; font-size: 10px; color: var(--muted); }
.integration-card :deep(.number-flow) { display: block; }
.integration-card :deep(span > span), .integration-card :deep(number-flow-vue) { display: block; font-size: 22px; font-weight: 750; color: var(--ink); line-height: 1.25; }
.ui-inspiration { display: block; padding: 12px; border: 1px solid var(--rule); border-radius: 12px; background: var(--paper-light); }
.ui-inspiration__heading { display: flex; align-items: center; justify-content: space-between; font-size: 13px; font-weight: 700; margin-bottom: 10px; }
.ui-inspiration__preview { height: 84px; overflow: hidden; border-radius: 7px; background: var(--acid-soft); }
.ui-inspiration__preview img { width: 100%; height: 100%; object-fit: cover; transition: transform .3s ease; }
.ui-inspiration:hover img { transform: scale(1.04); }
.ui-inspiration__fallback { display: grid; height: 100%; place-items: center; color: var(--muted); letter-spacing: .12em; font-size: 12px; }
.ui-inspiration__caption { display: flex; justify-content: space-between; gap: 8px; font-size: 10px; margin-top: 9px; color: var(--muted); }
.ui-inspiration__caption > span:first-child { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ui-inspiration__caption > span:last-child { white-space: nowrap; font-size: 8px; letter-spacing: .08em; }
.dashboard-sidebar a:focus-visible { outline: 2px solid var(--ink); outline-offset: 3px; }
.dashboard-sidebar .digest-cta:focus-visible { outline-color: #d6fb53; }
@media (min-width: 1600px) {
  .dashboard-main { grid-template-columns: minmax(0, 1fr) 330px; gap: 20px; }
  .dashboard-heading { padding-right: 350px; }
  .dashboard-heading :deep(.stat-strip) { flex-basis: 740px; }
  .dashboard-sidebar { position: relative; }
  .sidebar-motto { display: block; position: absolute; bottom: calc(100% + 28px); }
}
@media (max-width: 1199px) {
  .dashboard-heading { flex-wrap: wrap; gap: 16px; }
  .dashboard-heading :deep(.stat-strip) { flex: 1 1 100%; }
  .dashboard-main { grid-template-columns: minmax(0, 1fr) 260px; }
}
@media (max-width: 899px) {
  .dashboard-page { padding: 20px 14px 28px; }
  .dashboard-main { grid-template-columns: minmax(0, 1fr); }
  .dashboard-sidebar { display: grid; grid-template-columns: 1fr 1fr; align-items: start; }
}
@media (max-width: 539px) {
  .dashboard-heading__copy { min-width: 0; }
  .dashboard-sidebar { display: flex; }
}
@media (prefers-reduced-motion: reduce) {
  .ui-inspiration__preview img { transition: none; }
}
</style>
