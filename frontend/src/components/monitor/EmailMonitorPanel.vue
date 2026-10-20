<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import '@/i18n/locales/monitorActivity'
import { activityApi, type EmailMonitoring, type EmailQuota } from '@/services/monitor/activityApi'
import MonitorMetricCard from './MonitorMetricCard.vue'

const { t } = useI18n()
const data = ref<EmailMonitoring | null>(null)
const loading = ref(false)
const failed = ref(false)
let active = true
let poll: ReturnType<typeof setInterval> | undefined
const alerts = computed(() => [...(data.value?.alerts ?? [])].sort((a, b) =>
  Number(b.active) - Number(a.active) || b.opened_at.localeCompare(a.opened_at)))
const cstTime = (value: string) => new Date(value).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false })
const percent = (quota: EmailQuota) => quota.limit === null ? null : quota.limit === 0 ? 100 : quota.used * 100 / quota.limit
const quotaText = (quota: EmailQuota) => `${quota.used} / ${quota.limit ?? t('monitorActivity.unlimited')}`
async function load() {
  if (loading.value) return
  loading.value = true
  try {
    const result = await activityApi.email()
    if (active) { data.value = result; failed.value = false }
  } catch { if (active) failed.value = true }
  finally { if (active) loading.value = false }
}
onMounted(() => {
  void load()
  poll = setInterval(() => { if (document.visibilityState === 'visible') void load() }, 60_000)
})
onBeforeUnmount(() => { active = false; clearInterval(poll) })
</script>

<template>
  <section class="glass-card min-w-0 p-5" aria-labelledby="email-monitor-heading">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <h3 id="email-monitor-heading" class="monitor-section-title text-sm font-semibold">{{ t('monitorActivity.email') }}</h3>
      <button class="monitor-btn-secondary" :disabled="loading" @click="load">{{ t(loading ? 'common.refreshing' : 'common.refresh') }}</button>
    </div>
    <p class="monitor-caption mt-2 text-xs leading-5">{{ t('monitorActivity.emailDescription') }}</p>
    <p v-if="failed" role="alert" class="monitor-status-error mt-3 text-sm">{{ t('monitorActivity.loadFailed') }}</p>
    <p v-if="loading && !data" class="monitor-caption mt-4">{{ t('common.loading') }}</p>
    <template v-if="data">
      <p v-if="data.stale" role="status" class="monitor-status-error mt-3 rounded-md p-3 text-xs">{{ t(data.checked_at ? 'monitorActivity.stale' : 'monitorActivity.pendingCheck') }}</p>
      <p v-if="data.recipient_source === 'sender'" role="status" class="monitor-status-error mt-3 rounded-md p-3 text-xs">{{ t('monitorActivity.recipientFallback', { address: data.recipient }) }}</p>
      <p v-else-if="data.recipient_source === 'missing'" role="status" class="monitor-status-error mt-3 rounded-md p-3 text-xs">{{ t('monitorActivity.recipientMissing') }}</p>
      <div class="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-3">
        <MonitorMetricCard :label="t('monitorActivity.accepted')" :value="data.local?.accepted_24h ?? '—'" :note="t('monitorActivity.acceptedNote')" />
        <MonitorMetricCard :label="t('monitorActivity.failed')" :value="data.local?.failed_24h ?? '—'" :note="t('monitorActivity.localNote')" />
        <MonitorMetricCard :label="t('monitorActivity.alerts')" :value="data.checked_at ? alerts.filter(item => item.active).length : '—'" :note="t('monitorActivity.alertRecipient', { address: data.recipient ?? '—' })" />
      </div>
      <article v-for="provider in data.providers" :key="provider.name" class="mt-5 rounded-xl border p-4">
        <div class="flex flex-wrap items-center gap-3 text-sm">
          <h4 class="font-semibold">{{ provider.name }}</h4>
          <span class="monitor-caption text-xs">{{ provider.host }}:{{ provider.port }}</span>
          <span class="monitor-badge" :class="provider.smtp.status === 'ok' ? 'monitor-status-success' : 'monitor-status-error'">{{ t(provider.smtp.status === 'ok' ? 'monitorActivity.smtpOk' : 'monitorActivity.smtpFailed') }}</span>
          <span v-if="provider.smtp.error" class="monitor-caption text-xs">{{ provider.smtp.error }}</span>
        </div>
        <p v-if="provider.usage_error" role="status" class="monitor-status-error mt-3 text-xs">{{ t('monitorActivity.usageUnavailable') }} · {{ provider.usage_error }}</p>
        <div v-if="provider.usage" class="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2">
          <MonitorMetricCard v-for="period in (['daily', 'monthly'] as const)" :key="period" :label="t('monitorActivity.' + period)" :value="quotaText(provider.usage[period])">
            <template v-if="percent(provider.usage[period]) !== null">
              <progress class="h-2 w-full" :value="Math.min(100, percent(provider.usage[period])!)" max="100" :aria-label="t('monitorActivity.' + period)" />
              <span>{{ percent(provider.usage[period])!.toFixed(1) }}%</span>
            </template>
            <span>{{ t('monitorActivity.resets', { time: cstTime(provider.usage[period].resets_at) }) }}</span>
          </MonitorMetricCard>
        </div>
        <p v-else-if="!provider.usage_error" class="monitor-caption mt-3 text-xs">{{ t('monitorActivity.noQuota') }}</p>
        <p v-if="provider.events_error" class="monitor-status-error mt-3 text-xs">{{ t('monitorActivity.eventsUnavailable') }} · {{ provider.events_error }}</p>
        <template v-if="provider.recent">
          <p class="monitor-caption mt-4 text-xs leading-5">{{ t('monitorActivity.recent', { n: provider.recent.count }) }}</p>
          <div class="mt-2 flex flex-wrap gap-2">
            <span v-for="(count, status) in provider.recent.statuses" :key="status" class="monitor-badge tabular-nums">{{ t('monitorActivity.events.' + status) }} {{ count }}</span>
          </div>
        </template>
      </article>
      <div class="mt-5">
        <h4 class="text-sm font-semibold">{{ t('monitorActivity.alertLog') }}</h4>
        <p class="monitor-caption mt-2 text-xs leading-5">{{ t('monitorActivity.alertPolicy') }}</p>
        <p v-if="!alerts.length" class="monitor-caption mt-3 text-xs">{{ t('monitorActivity.noAlerts') }}</p>
        <ul v-else class="mt-3 space-y-3">
          <li v-for="alert in alerts" :key="alert.id" class="rounded-lg border p-3 text-xs">
            <span class="monitor-badge" :class="alert.active ? 'monitor-status-error' : 'monitor-status-success'">{{ t(alert.active ? 'monitorActivity.activeAlert' : 'monitorActivity.resolved') }}</span>
            <span class="ml-2 monitor-caption">{{ cstTime(alert.opened_at) }} CST</span>
            <p class="mt-2 leading-5">{{ alert.current_detail ?? alert.detail }}</p>
            <p class="monitor-caption mt-1">{{ t(alert.notified_at ? 'monitorActivity.notificationAccepted' : 'monitorActivity.notificationPending') }}<span v-if="alert.notification_error"> · {{ alert.notification_error }}</span></p>
          </li>
        </ul>
      </div>
      <p class="monitor-caption mt-4 text-xs leading-5">{{ t('monitorActivity.localSince', { time: cstTime(data.tracking_started_at) }) }}</p>
      <p v-if="data.checked_at" class="monitor-caption mt-1 text-xs">{{ t('monitorActivity.asOf', { time: cstTime(data.checked_at) }) }}</p>
    </template>
  </section>
</template>

<style scoped>
progress { accent-color: var(--projects-accent); }
</style>
