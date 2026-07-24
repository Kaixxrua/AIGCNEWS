<script setup lang="ts">
import { useDashboardData } from '../composables/useDashboardData'
import { useDashboardStats } from '../composables/useDashboardStats'
import DashboardEmptyState from '../components/dashboard/DashboardEmptyState.vue'
import DashboardOverviewPanel from '../components/dashboard/DashboardOverviewPanel.vue'
import DashboardRankingPanel from '../components/dashboard/DashboardRankingPanel.vue'
import { CalendarDays } from 'lucide-vue-next'
import type { Stats } from '../features/dashboard/dashboardViewModel'

defineOptions({ name: 'DashboardView' })

let currentStats: () => Stats = () => ({})
const {
  updateStatSources,
  updateVisitorSources,
  disableCountUp,
  getAnimatedValue,
  getVisitorDisplayValue,
} = useDashboardStats(() => currentStats())

const {
  activeTab,
  activePeriod,
  isPeriodDisabled,
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
  selectSourceTab,
  onDateChange,
  hasData,
} = useDashboardData({
  updateStatSources,
  updateVisitorSources,
  disableCountUp,
})
currentStats = () => stats.value

</script>

<template>
  <div class="dashboard-page flex h-full flex-col gap-2 overflow-y-auto px-6 py-3 pb-16">

    <!-- 页头 — 简洁标题 -->
    <div class="stagger-enter flex items-center justify-between shrink-0">
      <h1 class="text-xl font-semibold text-stone-800 tracking-tight font-serif">Dashboard</h1>
      <div v-if="!loading && isViewingHistory" class="flex items-center gap-1.5 text-xs text-stone-400">
        <CalendarDays class="h-3.5 w-3.5" />
        <span class="text-stone-700 font-medium">{{ currentDate }}</span>
      </div>
    </div>

    <!-- 错误提示 -->
    <div
      v-if="errorMsg"
      class="shrink-0 glass-card flex items-center gap-2 px-5 py-3 text-sm text-rose-600"
    >
      <svg class="h-4 w-4 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/>
      </svg>
      {{ errorMsg }}
    </div>

    <!-- 顶部区域：统计卡片 + 日历 -->
    <DashboardOverviewPanel
      :loading="loading"
      :active-tab="activeTab"
      :current-date="currentDate"
      :available-dates="availableDates"
      :get-animated-value="getAnimatedValue"
      :get-visitor-display-value="getVisitorDisplayValue"
      @select-source="selectSourceTab"
      @date-change="onDateChange"
    />

    <!-- 静默期专用空状态 (Embargo Empty State) -->
    <DashboardEmptyState v-if="!loading && isEmbargoed" variant="embargoed" />

    <!-- 全局空状态（非静默期） -->
    <DashboardEmptyState
      v-else-if="!loading && !hasData && !tabLoading && !isEmbargoed"
      variant="no-data"
    />

    <!-- 榜单面板（静默期时隐藏） -->
    <DashboardRankingPanel
      v-if="!loading && hasData && !isEmbargoed"
      :active-tab="activeTab"
      :active-period="activePeriod"
      :tab-list="tabList"
      :tab-loading="tabLoading"
      :is-viewing-history="isViewingHistory"
      :is-finalized="isFinalized"
      :is-period-disabled="isPeriodDisabled"
      @select-source="selectSourceTab"
      @select-period="activePeriod = $event"
    />
  </div>
</template>

<style scoped>
.dashboard-page {
  --paper: #f3f0e6;
  --paper-light: #fffdf5;
  --ink: #11110f;
  --muted: #68655d;
  --acid: #c7f432;
  --acid-soft: #f1f8d2;
  color: var(--ink);
  background-color: var(--paper);
  background-image: linear-gradient(rgba(17, 17, 15, .035) 1px, transparent 1px);
  background-size: 100% 32px;
  font-family: Inter, ui-sans-serif, system-ui, sans-serif;
}

.dashboard-page :deep(.font-serif) { font-family: Inter, ui-sans-serif, system-ui, sans-serif; }
.dashboard-page :deep(h1),
.dashboard-page :deep(h2),
.dashboard-page :deep(h3) { color: var(--ink); font-weight: 850; letter-spacing: -.04em; }
.dashboard-page :deep(.glass-card) {
  border: 1px solid var(--ink);
  border-radius: 5px;
  background: var(--paper-light);
  box-shadow: 3px 3px 0 var(--ink);
  backdrop-filter: none;
}
.dashboard-page :deep(.card-hover:hover) { border-color: var(--ink); background: var(--acid-soft); box-shadow: 3px 3px 0 var(--ink); transform: none; }
.dashboard-page :deep(.text-stone-300),
.dashboard-page :deep(.text-stone-400) { color: var(--muted); }
.dashboard-page :deep(.rounded-full),
.dashboard-page :deep(.rounded-xl),
.dashboard-page :deep(.rounded-2xl) { border-radius: 4px; }

.dashboard-page :deep(.bg-slate-800) { border: 1px solid var(--ink); color: var(--ink); background: var(--acid); box-shadow: 3px 3px 0 var(--ink); }
.dashboard-page :deep(.bg-slate-800:hover) { color: var(--ink); background: var(--acid); }
.dashboard-page :deep(.bg-slate-800 .text-white),
.dashboard-page :deep(.bg-slate-800 .text-slate-300) { color: inherit; }
.dashboard-page :deep(.dashboard-source-card--active) {
  border-color: var(--ink);
  background: var(--acid);
  box-shadow: inset 0 -3px 0 var(--ink), 3px 3px 0 var(--ink);
}
.dashboard-page :deep(.dashboard-source-card--active .text-blue-600),
.dashboard-page :deep(.dashboard-source-card--active .text-gray-800),
.dashboard-page :deep(.dashboard-source-card--active .text-amber-600),
.dashboard-page :deep(.dashboard-source-card--active .text-rose-600),
.dashboard-page :deep(.dashboard-source-card--active .text-orange-500) { color: var(--ink) !important; }

@media (prefers-reduced-motion: reduce) {
  .dashboard-page *, .dashboard-page *::before, .dashboard-page *::after { transition-duration: .01ms !important; animation-duration: .01ms !important; }
}
</style>
