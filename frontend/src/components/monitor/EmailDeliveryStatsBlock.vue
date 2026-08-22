<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
const { t } = useI18n()
import { type EmailDeliveryDayStat } from '@/features/monitor/monitorModel'

// 全渠道邮件投递统计（push_deliveries 台账，不分 SMTP / 邮件池），
// SMTP 配置卡与邮件池卡共用本块
const props = defineProps<{
  stats: EmailDeliveryDayStat[]
  statsLoading: boolean
}>()

// 后端按 Asia/Shanghai 自然日归日；前端须用同一时区求"今天"，否则跨时区
// 管理员在 UTC±边缘时段会找不到今日行
const todayStat = computed(() => {
  const today = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(new Date())
  return props.stats.find((day) => day.date === today) ?? null
})
</script>

<template>
  <div class="monitor-check-row mb-3 px-3 py-2 text-xs">
    <div class="flex flex-wrap items-center gap-x-2 gap-y-1">
      <span class="monitor-caption">{{ t('monitor.deliveryStats.title') }}</span>
      <template v-if="todayStat">
        <span class="badge monitor-status-success">{{ t('monitor.deliveryStats.todaySent', { count: todayStat.sent }) }}</span>
        <span v-if="todayStat.failed > 0" class="badge monitor-status-error">{{ t('monitor.deliveryStats.todayFailed', { count: todayStat.failed }) }}</span>
      </template>
      <span v-else-if="!statsLoading" class="monitor-caption">{{ t('monitor.deliveryStats.todayEmpty') }}</span>
    </div>
    <div v-if="stats.length" class="mt-1.5 flex flex-wrap gap-x-3 gap-y-0.5 monitor-caption">
      <span v-for="day in stats" :key="day.date" class="whitespace-nowrap">
        {{ day.date.slice(5) }} · {{ t('monitor.deliveryStats.daySent', { count: day.sent }) }}<template v-if="day.failed > 0"> · <span class="delivery-stats-failed">{{ t('monitor.deliveryStats.dayFailed', { count: day.failed }) }}</span></template>
      </span>
    </div>
    <div v-else-if="!statsLoading" class="mt-1.5 monitor-caption">{{ t('monitor.deliveryStats.empty') }}</div>
  </div>
</template>

<style scoped>
/* 失败计数用主题错误色内联强调（先例：GithubEnrichmentPanel 的 --error-accent 用法） */
.delivery-stats-failed {
  color: var(--error-accent);
  font-weight: 600;
}
</style>
