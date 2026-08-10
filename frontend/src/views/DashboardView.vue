<script setup lang="ts">
import { onActivated, onBeforeUnmount, onDeactivated, onMounted } from 'vue'
import { useIntervalFn } from '@vueuse/core'
import { useI18n } from 'vue-i18n'
import { useDashboardData } from '@/composables/useDashboardData'
import { useDashboardStats } from '@/composables/useDashboardStats'
import GlassCalendar from '@/components/GlassCalendar.vue'
import SpinnerLoader from '@/components/SpinnerLoader.vue'
import DashboardEmptyState from '@/components/dashboard/DashboardEmptyState.vue'
import DashboardOverviewPanel from '@/components/dashboard/DashboardOverviewPanel.vue'
import DashboardRankingPanel from '@/components/dashboard/DashboardRankingPanel.vue'
import RollingNumber from '@/components/dashboard/RollingNumber.vue'
import { CalendarDays, ArrowRight, MailPlus, Plug } from 'lucide-vue-next'
import { useAuthStore } from '@/stores/authStore'
import type { Stats } from '@/features/dashboard/dashboardViewModel'

defineOptions({ name: 'DashboardView' })
const { t } = useI18n()
const authStore = useAuthStore()

let currentStats: () => Stats = () => ({})
const {
  statValues,
  visitorValues,
  userParts,
  mcpTotalCalls,
  updateStatSources,
  updateVisitorSources,
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
  refreshLiveStats,
} = useDashboardData({
  updateStatSources,
  updateVisitorSources,
})
currentStats = () => stats.value

/* 每 10s 轮询实时计数：仅变化的数字滚筒滚动差位（如 1306→2309 只滚千位与个位），
   无变化则完全静止。KeepAlive 停用或卸载时暂停定时器。 */
const { pause: pauseLivePoll, resume: resumeLivePoll } = useIntervalFn(() => { void refreshLiveStats() }, 10_000, { immediate: false })
onMounted(resumeLivePoll)
onActivated(resumeLivePoll)
onDeactivated(pauseLivePoll)
onBeforeUnmount(pauseLivePoll)

</script>

<template>
  <div class="dashboard-page flex h-full flex-col gap-1.5 overflow-y-auto px-6 py-2.5 pb-5">

    <!-- 页头 — 简洁标题 -->
    <div class="stagger-enter flex items-center justify-between shrink-0">
      <h1 class="text-xl font-semibold text-stone-800 tracking-tight font-serif">{{ t('dashboard.title') }}</h1>
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

    <!-- 顶部统计带：所有指标合并为一行分段条；加载期间整条隐藏，避免出现空段 -->
    <DashboardOverviewPanel
      v-if="!loading"
      :loading="loading"
      :active-tab="activeTab"
      :stat-values="statValues"
      :visitor-values="visitorValues"
      :user-parts="userParts"
      @select-source="selectSourceTab"
    />

    <!-- 主区域：榜单/空态占满剩余高度，日历与公众号入口收入右侧栏 -->
    <div class="flex min-h-0 flex-1 flex-col gap-2 lg:flex-row">
      <!-- 加载中：仅转圈，数据就绪后内容卡片直接出现 -->
      <SpinnerLoader v-if="loading" class="order-2 min-h-[360px] min-w-0 flex-1 lg:order-1" />

      <!-- 静默期专用空状态 (Embargo Empty State) -->
      <DashboardEmptyState v-if="!loading && isEmbargoed" variant="embargoed" class="order-2 min-w-0 lg:order-1" />

      <!-- 全局空状态（非静默期） -->
      <DashboardEmptyState
        v-else-if="!loading && !hasData && !tabLoading && !isEmbargoed"
        variant="no-data"
        class="order-2 min-w-0 lg:order-1"
      />

      <!-- 榜单面板（静默期时隐藏） -->
      <DashboardRankingPanel
        v-if="!loading && hasData && !isEmbargoed"
        class="order-2 min-w-0 lg:order-1"
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

      <aside v-if="!loading" class="order-1 flex w-full max-w-[320px] shrink-0 flex-col gap-2 self-center lg:order-2 lg:w-[212px] lg:max-w-none lg:self-stretch">
          <GlassCalendar
            :model-value="currentDate"
            :available-dates="availableDates"
            @update:model-value="onDateChange"
          />
          <!-- 公众号快捷入口（仅管理员） -->
          <RouterLink
            v-if="authStore.isAdmin"
            to="/wechat"
            class="stagger-enter glass-card card-hover flex min-h-[44px] shrink-0 items-center justify-between gap-2 px-2.5 py-1.5 transition-colors"
            style="animation-delay: 0.3s"
          >
            <span class="flex items-center gap-2">
              <span class="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-emerald-100 text-emerald-600">
                <svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M9.5 4C5.36 4 2 6.91 2 10.5c0 1.96 1.13 3.72 2.94 4.96L4 19l3.85-1.93c.67.18 1.38.28 2.12.28.23 0 .46-.01.68-.03"/>
                  <path d="M14.5 9c3.87 0 7 2.69 7 6s-3.13 6-7 6c-.63 0-1.24-.06-1.83-.18L11 21.5l.5-2.5c-1.5-1.1-2.5-2.77-2.5-4.62 0-3.31 3.13-6 7-6z"/>
                </svg>
              </span>
              <span class="text-xs font-medium text-stone-500">{{ t('wechat.panelTitle') }}</span>
            </span>
            <svg class="h-4 w-4 text-stone-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <polyline points="9 18 15 12 9 6" />
            </svg>
          </RouterLink>

          <!-- 每日简报订阅入口 -->
          <RouterLink
            to="/report"
            class="stagger-enter glass-card card-hover group flex flex-col gap-2 px-3 py-2.5 transition-colors"
            style="animation-delay: 0.35s"
          >
            <span class="flex items-center gap-2">
              <span class="flex h-7 w-7 shrink-0 items-center justify-center rounded-[4px] border border-ink bg-accent text-accent-ink">
                <MailPlus class="h-4 w-4" />
              </span>
              <span class="text-sm font-bold text-stone-800">{{ t('dashboard.digest.title') }}</span>
            </span>
            <span class="text-2xs leading-relaxed text-stone-400">{{ t('dashboard.digest.description') }}</span>
            <span class="digest-cta mt-auto inline-flex items-center justify-center gap-1 rounded-[4px] border border-ink bg-ink px-2 py-1.5 text-xs font-bold text-accent transition-colors group-hover:bg-accent group-hover:text-accent-ink">
              {{ t('dashboard.digest.cta') }}
              <ArrowRight class="h-3.5 w-3.5" />
            </span>
          </RouterLink>

          <!-- MCP 总调用次数 -->
          <div
            class="stagger-enter glass-card flex items-center gap-2.5 px-3 py-2.5"
            style="animation-delay: 0.4s"
          >
            <span class="flex h-7 w-7 shrink-0 items-center justify-center rounded-[4px] border border-ink bg-accent text-accent-ink">
              <Plug class="h-4 w-4" />
            </span>
            <span class="flex min-w-0 flex-col">
              <span class="text-2xs font-semibold text-stone-400">{{ t('dashboard.mcpCalls.title') }}</span>
              <RollingNumber :value="mcpTotalCalls" grouping class="text-base font-extrabold tabular-nums" />
            </span>
          </div>
      </aside>
    </div>
  </div>
</template>

<style scoped>
.dashboard-page {
  --paper: var(--projects-paper);
  --paper-light: var(--projects-paper-light);
  --ink: var(--projects-accent);
  --muted: var(--dash-muted);
  --acid: var(--projects-acid);
  --acid-soft: var(--projects-acid-soft);
  color: var(--ink);
  background-color: var(--paper);
  background-image: linear-gradient(rgb(var(--ink-grid-rgb) / .035) 1px, transparent 1px);
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
  box-shadow: 3px 3px 0 var(--shadow-hard);
  backdrop-filter: none;
}
.dashboard-page :deep(.card-hover:hover) { border-color: var(--ink); background: var(--acid-soft); box-shadow: 3px 3px 0 var(--shadow-hard); transform: none; }
.dashboard-page :deep(.text-stone-300),
.dashboard-page :deep(.text-stone-400) { color: var(--muted); }
/* 深色下 GitHub/X 指标的字面灰色不可读，统一映射为 ink */
:root[data-theme='dark'] .dashboard-page :deep(.text-gray-800),
:root[data-theme='dark'] .dashboard-page :deep(.text-gray-600) { color: var(--ink); }
/* 深色下 ink 按钮底色翻为浅色，简报 CTA 标签改用 paper 保证对比度 */
:root[data-theme='dark'] .dashboard-page .digest-cta { color: var(--paper); }
.dashboard-page :deep(.rounded-full),
.dashboard-page :deep(.rounded-xl),
.dashboard-page :deep(.rounded-2xl) { border-radius: 4px; }

@media (prefers-reduced-motion: reduce) {
  .dashboard-page *, .dashboard-page *::before, .dashboard-page *::after { transition-duration: .01ms !important; animation-duration: .01ms !important; }
}
</style>
