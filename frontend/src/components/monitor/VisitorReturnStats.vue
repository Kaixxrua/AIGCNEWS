<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import '@/i18n/locales/monitorActivity'
import { formatReturnRate, type VisitorReturnDay, type VisitorReturns } from '@/services/monitor/activityApi'
import MonitorMetricCard from './MonitorMetricCard.vue'

const props = defineProps<{ data: VisitorReturns }>()
const { t } = useI18n()
const today = computed(() => props.data.days[0])
const collecting = computed(() => today.value?.total_visitors != null && today.value.returning_visitors === null)
const trackedDays = computed(() => props.data.days.filter(row => row.coverage !== 'unavailable'))
const fraction = (row: VisitorReturnDay) => t('monitorActivity.browserFraction', {
  returning: row.returning_visitors ?? '—', visitors: row.total_visitors ?? '—',
})
const cstTime = (value: string) => new Date(value).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false })
</script>

<template>
  <div class="visitor-return-stats mt-6 border-t pt-4">
    <h4 class="monitor-section-title text-sm font-semibold">{{ t('monitorActivity.browserReturns') }}</h4>
    <p class="monitor-caption mt-2 text-xs leading-5">{{ t('monitorActivity.browserSince', { time: cstTime(data.tracking_started_at) }) }}</p>
    <p v-if="collecting" class="monitor-caption mt-2 text-sm leading-6" role="status">{{ t('monitorActivity.browserCollecting', { count: today?.total_visitors }) }}</p>
    <details class="mt-2 text-xs">
      <summary class="monitor-caption cursor-pointer">{{ t('monitorActivity.metricDefinitions') }}</summary>
      <p class="monitor-caption mt-2 leading-5">{{ t('monitorActivity.browserDefinition') }}</p>
      <p class="monitor-caption mt-1 leading-5">{{ t('monitorActivity.browserScope') }}</p>
    </details>
    <div v-if="today && !collecting" class="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-3">
      <MonitorMetricCard :label="t('monitorActivity.browserRateToday')" :value="formatReturnRate(today.return_rate)" :note="fraction(today)" />
      <MonitorMetricCard :label="t('monitorActivity.browserReturningToday')" :value="today.returning_visitors ?? '—'" :note="t('monitorActivity.browserReturningNote')" />
      <MonitorMetricCard :label="t('monitorActivity.browserVisitorsToday')" :value="today.total_visitors ?? '—'" :note="t('monitorActivity.browserVisitorsNote')" />
    </div>
    <div v-if="!collecting && trackedDays.length" class="mt-3 overflow-x-auto" role="region" :aria-label="t('monitorActivity.browserReturns')" tabindex="0">
      <table class="w-full min-w-[560px] text-left text-xs tabular-nums">
        <caption class="sr-only">{{ t('monitorActivity.browserReturns') }}</caption>
        <thead><tr class="border-b">
          <th class="py-3">{{ t('monitorActivity.date') }}</th>
          <th>{{ t('monitorActivity.browserVisitors') }}</th>
          <th>{{ t('monitorActivity.browserReturning') }}</th>
          <th>{{ t('monitorActivity.browserRate') }}</th>
          <th>{{ t('monitorActivity.coverage') }}</th>
        </tr></thead>
        <tbody><tr v-for="row in trackedDays" :key="row.day" class="border-b">
          <th scope="row" class="whitespace-nowrap py-3 font-normal">{{ row.day }}</th>
          <td>{{ row.total_visitors ?? '—' }}</td>
          <td>{{ row.returning_visitors ?? '—' }}</td>
          <td :title="fraction(row)">{{ formatReturnRate(row.return_rate) }}</td>
          <td class="monitor-caption">{{ t('monitorActivity.' + row.coverage) }}</td>
        </tr></tbody>
      </table>
    </div>
  </div>
</template>
