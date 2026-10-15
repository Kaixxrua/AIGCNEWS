<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import '@/i18n/locales/monitorActivity'
import { activityApi, formatReturnRate, type ReturnVisitDay, type ReturnVisits } from '@/services/monitor/activityApi'
import MonitorMetricCard from './MonitorMetricCard.vue'
import VisitorReturnStats from './VisitorReturnStats.vue'

const { t } = useI18n()
const data = ref<ReturnVisits | null>(null)
const loading = ref(false)
const failed = ref(false)
const days = ref(7)
const today = computed(() => data.value?.days[0])
const fraction = (row: ReturnVisitDay, kind: 'return' | 'registration') => t(`monitorActivity.${kind}Fraction`, {
  returning: row.returning_users ?? '—', visitors: row.total_visitors ?? '—', new: row.new_users ?? '—',
})
let active = true
let poll: ReturnType<typeof setInterval> | undefined
async function load() {
  if (loading.value) return
  loading.value = true
  try {
    const result = await activityApi.returnVisits(days.value)
    if (active) { data.value = result; failed.value = false }
  } catch { if (active) failed.value = true }
  finally { if (active) loading.value = false }
}
const cstTime = (value: string) => new Date(value).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false })
onMounted(() => {
  void load()
  poll = setInterval(() => { if (document.visibilityState === 'visible') void load() }, 60_000)
})
onBeforeUnmount(() => { active = false; clearInterval(poll) })
</script>

<template>
  <section class="glass-card min-w-0 p-5" aria-labelledby="return-visits-heading">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <h3 id="return-visits-heading" class="monitor-section-title text-sm font-semibold">{{ t('monitorActivity.returns') }}</h3>
      <div class="flex items-center gap-2">
        <select v-model="days" :aria-label="t('monitorActivity.range')" class="monitor-input return-range" :disabled="loading" @change="load">
          <option :value="7">{{ t('monitorActivity.days', { n: 7 }) }}</option>
          <option :value="30">{{ t('monitorActivity.days', { n: 30 }) }}</option>
          <option :value="90">{{ t('monitorActivity.days', { n: 90 }) }}</option>
        </select>
        <button class="monitor-btn-secondary" :disabled="loading" @click="load">{{ t(loading ? 'common.refreshing' : 'common.refresh') }}</button>
      </div>
    </div>
    <p v-if="failed" role="alert" class="monitor-status-error mt-3 text-sm">{{ t('monitorActivity.loadFailed') }}</p>
    <p v-if="loading && !data" class="monitor-caption mt-4">{{ t('common.loading') }}</p>
    <template v-if="data && today">
      <div class="account-return-stats mt-4">
        <h4 class="monitor-section-title text-sm font-semibold">{{ t('monitorActivity.accountDetails') }}</h4>
        <div class="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
          <MonitorMetricCard :label="t('monitorActivity.visitorsToday')" :value="today.total_visitors ?? '—'" :note="t('monitorActivity.allVisitors')" />
          <MonitorMetricCard :label="t('monitorActivity.newToday')" :value="today.new_users ?? '—'" :note="t('monitorActivity.newAccounts')" />
          <MonitorMetricCard :label="t('monitorActivity.registrationToday')" :value="formatReturnRate(today.registration_rate)" :note="fraction(today, 'registration')" />
          <MonitorMetricCard :label="t('monitorActivity.activeToday')" :value="today.active_users ?? '—'" :note="t('monitorActivity.uniqueAccounts')" />
          <MonitorMetricCard :label="t('monitorActivity.returningToday')" :value="today.returning_users ?? '—'" :note="t('monitorActivity.oldAccount')" />
          <MonitorMetricCard :label="t('monitorActivity.rateToday')" :value="formatReturnRate(today.return_rate)" :note="fraction(today, 'return')" />
        </div>
        <details class="mt-3 text-xs">
          <summary class="monitor-caption cursor-pointer">{{ t('monitorActivity.metricDefinitions') }}</summary>
          <p class="monitor-caption mt-2 leading-5">{{ t('monitorActivity.definition') }}</p>
          <p class="monitor-caption mt-1 leading-5">{{ t('monitorActivity.registrationDefinition') }}</p>
          <p class="monitor-caption mt-1 leading-5">{{ t('monitorActivity.visitorScope') }}</p>
          <p class="monitor-caption mt-1 leading-5">{{ t('monitorActivity.since', { time: cstTime(data.tracking_started_at) }) }}</p>
        </details>
        <div class="mt-3 overflow-x-auto" role="region" :aria-label="t('monitorActivity.returns')" tabindex="0">
          <table class="w-full min-w-[760px] text-left text-xs tabular-nums">
            <caption class="sr-only">{{ t('monitorActivity.returns') }}</caption>
            <thead><tr class="border-b"><th class="py-3">{{ t('monitorActivity.date') }}</th><th>{{ t('monitorActivity.visitors') }}</th><th>{{ t('monitorActivity.active') }}</th><th>{{ t('monitorActivity.returning') }}</th><th>{{ t('monitorActivity.new') }}</th><th>{{ t('monitorActivity.rate') }}</th><th>{{ t('monitorActivity.registrationRate') }}</th><th>{{ t('monitorActivity.coverage') }}</th></tr></thead>
            <tbody><tr v-for="row in data.days" :key="row.day" class="border-b">
              <th scope="row" class="whitespace-nowrap py-3 font-normal">{{ row.day }}</th>
              <td>{{ row.total_visitors ?? '—' }}</td><td>{{ row.active_users ?? '—' }}</td><td>{{ row.returning_users ?? '—' }}</td><td>{{ row.new_users ?? '—' }}</td>
              <td :title="fraction(row, 'return')">{{ formatReturnRate(row.return_rate) }}</td>
              <td :title="fraction(row, 'registration')">{{ formatReturnRate(row.registration_rate) }}</td><td class="monitor-caption">{{ t('monitorActivity.' + row.coverage) }}</td>
            </tr></tbody>
          </table>
        </div>
      </div>
      <VisitorReturnStats v-if="data.visitor_returns" :data="data.visitor_returns" />
      <p v-else class="monitor-caption mt-3 text-xs">{{ t('monitorActivity.browserUnavailable') }}</p>
      <p class="monitor-caption mt-3 text-xs">{{ t('monitorActivity.asOf', { time: cstTime(data.as_of) }) }}</p>
    </template>
  </section>
</template>

<style scoped>
.return-range {
  min-height: 32px;
  padding: 4px 8px;
  color: var(--ink);
  background: var(--paper-raised);
  border: 1px solid var(--rule);
  border-radius: 6px;
  font-size: 12px;
}
.return-range:focus-visible { outline: 2px solid var(--ink); outline-offset: 2px; }
</style>
