<script setup lang="ts">
import { onBeforeUnmount, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { CircleDollarSign } from 'lucide-vue-next'
import SpinnerLoader from '@/components/SpinnerLoader.vue'
import { useRevenueStatsController } from '@/composables/useRevenueStatsController'

const { t } = useI18n()
const { data, loading, errorMsg, load, dispose } = useRevenueStatsController({ translate: t })

const windows = [
  { key: 'today', label: 'monitor.revenue.today' },
  { key: 'week', label: 'monitor.revenue.week' },
  { key: 'month', label: 'monitor.revenue.month' },
  { key: 'year', label: 'monitor.revenue.year' },
] as const

const amount = (cents: number | undefined) => (Number(cents) / 100).toFixed(2)

onMounted(load)
onBeforeUnmount(dispose)
</script>

<template>
  <div class="revenue-stats-panel stagger-enter glass-card shrink-0 p-5" style="animation-delay: 0.2s">
    <div class="flex items-center gap-2">
      <CircleDollarSign class="h-4 w-4 monitor-caption" />
      <h3 class="monitor-section-title text-sm font-semibold">{{ t('monitor.revenue.title') }}</h3>
    </div>
    <p class="monitor-caption mt-1.5 text-xs leading-5">{{ t('monitor.revenue.description') }}</p>
    <div v-if="errorMsg" class="mt-3 flex items-center justify-between rounded-md border px-4 py-2 text-xs monitor-status-error">
      <span>{{ errorMsg }}</span>
      <button class="ml-3 opacity-70 hover:opacity-100" @click="errorMsg = ''">✕</button>
    </div>
    <SpinnerLoader v-if="loading && !data" class="min-h-[120px]" />
    <div v-else-if="data" class="revenue-stats-tiles mt-4">
      <div v-for="item in windows" :key="item.key" class="revenue-stat-tile">
        <span class="revenue-stat-label">{{ t(item.label) }}</span>
        <div class="revenue-stat-line"><span>{{ t('monitor.revenue.cny') }}</span><strong>¥{{ amount(data[item.key].cny_amount_cents) }}</strong></div>
        <div class="revenue-stat-line"><span>{{ t('monitor.revenue.usd') }}</span><strong>${{ amount(data[item.key].usd_amount_cents) }}</strong></div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.revenue-stats-tiles { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }
.revenue-stat-tile { display: flex; flex-direction: column; gap: 10px; padding: 14px 16px; border: 1px solid var(--rule); border-radius: 10px; }
.revenue-stat-label { font-size: 12px; color: var(--ink-muted); font-weight: 700; }
.revenue-stat-line { display: flex; justify-content: space-between; gap: 8px; color: var(--ink-muted); font-size: 12px; }
.revenue-stat-line strong { color: var(--projects-accent); font-variant-numeric: tabular-nums; font-size: 16px; }
@media (max-width: 860px) { .revenue-stats-tiles { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 560px) { .revenue-stats-tiles { grid-template-columns: 1fr; } }
</style>
