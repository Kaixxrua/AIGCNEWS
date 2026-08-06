<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import type { GithubCrawlForm, GithubCrawlStatus } from '@/features/monitor/monitorModel'
import { getStatusConfig } from '@/features/monitor/monitorViewModel'

const { t } = useI18n()

const props = defineProps<{
  form: GithubCrawlForm
  crawling: boolean
  crawlPolling: boolean
  crawlStatus: GithubCrawlStatus | null
}>()

const emit = defineEmits<{
  'update:form': [form: GithubCrawlForm]
  start: []
}>()

const update = (patch: Partial<GithubCrawlForm>) => emit('update:form', { ...props.form, ...patch })
const updateNumber = (key: 'minStars' | 'maxStars' | 'limit', value: string) => {
  const parsed = Number.parseInt(value, 10)
  if (!Number.isNaN(parsed)) update({ [key]: parsed })
}
</script>

<template>
  <div class="stagger-enter glass-card shrink-0 p-5" style="animation-delay: 0.19s">
    <div class="flex items-center gap-2 mb-3">
      <svg class="h-4 w-4 monitor-caption" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
      <h3 class="monitor-section-title text-sm font-semibold">{{ t('monitor.crawl.title') }}</h3>
      <span class="ml-auto text-2xs monitor-caption">{{ t('monitor.crawl.autoEnrichHint') }}</span>
    </div>

    <div class="flex flex-wrap items-end gap-x-4 gap-y-3">
      <label class="flex flex-col gap-1">
        <span class="text-2xs monitor-caption">{{ t('monitor.crawl.minStars') }}</span>
        <input :value="form.minStars" type="number" min="0" class="input w-24 py-1.5 text-xs" @input="updateNumber('minStars', ($event.target as HTMLInputElement).value)" />
      </label>
      <label class="flex flex-col gap-1">
        <span class="text-2xs monitor-caption">{{ t('monitor.crawl.maxStars') }}</span>
        <input :value="form.maxStars" type="number" min="0" class="input w-24 py-1.5 text-xs" @input="updateNumber('maxStars', ($event.target as HTMLInputElement).value)" />
      </label>
      <label class="flex flex-col gap-1">
        <span class="text-2xs monitor-caption">{{ t('monitor.crawl.createdStart') }}</span>
        <input :value="form.createdStart" type="date" class="input w-auto py-1.5 text-xs" @input="update({ createdStart: ($event.target as HTMLInputElement).value })" />
      </label>
      <label class="flex flex-col gap-1">
        <span class="text-2xs monitor-caption">{{ t('monitor.crawl.createdEnd') }}</span>
        <input :value="form.createdEnd" type="date" class="input w-auto py-1.5 text-xs" @input="update({ createdEnd: ($event.target as HTMLInputElement).value })" />
      </label>
      <label class="flex flex-col gap-1">
        <span class="text-2xs monitor-caption">{{ t('monitor.crawl.pushedAfter') }}</span>
        <input :value="form.pushedAfter" type="date" class="input w-auto py-1.5 text-xs" @input="update({ pushedAfter: ($event.target as HTMLInputElement).value })" />
      </label>
      <label class="flex flex-col gap-1">
        <span class="text-2xs monitor-caption">{{ t('monitor.crawl.limit') }}</span>
        <input :value="form.limit" type="number" min="1" max="20000" class="input w-24 py-1.5 text-xs" @input="updateNumber('limit', ($event.target as HTMLInputElement).value)" />
      </label>

      <label class="monitor-check-row flex items-center gap-1.5 px-3 py-2 cursor-pointer select-none">
        <input :checked="form.enrich" type="checkbox" class="h-3.5 w-3.5" @change="update({ enrich: ($event.target as HTMLInputElement).checked })" />
        <span class="text-xs monitor-caption">{{ t('monitor.crawl.autoEnrich') }}</span>
      </label>
      <label class="monitor-check-row flex items-center gap-1.5 px-3 py-2 cursor-pointer select-none">
        <input :checked="form.dryRun" type="checkbox" class="h-3.5 w-3.5" @change="update({ dryRun: ($event.target as HTMLInputElement).checked })" />
        <span class="text-xs monitor-caption">{{ t('monitor.crawl.dryRun') }}</span>
      </label>

      <button class="monitor-btn-primary" :disabled="crawling || crawlPolling" @click="emit('start')">
        <svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"/></svg>
        {{ t(crawling || crawlPolling ? 'monitor.crawl.starting' : 'monitor.crawl.start') }}
      </button>
    </div>

    <div v-if="crawlStatus && crawlStatus.task_id" class="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1.5 monitor-divider border-t pt-3">
      <span class="badge" :class="[getStatusConfig(crawlStatus.task_status).bg]">
        <span class="status-dot shrink-0" :class="getStatusConfig(crawlStatus.task_status).dot" />
        {{ getStatusConfig(crawlStatus.task_status).labelKey ? t(`monitor.${getStatusConfig(crawlStatus.task_status).labelKey}`) : getStatusConfig(crawlStatus.task_status).rawLabel }}
      </span>
      <span class="text-xs monitor-caption tabular-nums">{{ t('monitor.crawl.progressIngested', { count: crawlStatus.candidates_upserted }) }}</span>
      <span class="text-xs monitor-caption tabular-nums">{{ t('monitor.crawl.progressEnriched', { done: crawlStatus.enriched_succeeded, total: crawlStatus.scope_total }) }}</span>
      <span v-if="crawlStatus.enriched_failed > 0" class="text-xs monitor-status-error px-2 py-0.5 rounded tabular-nums">{{ t('monitor.crawl.progressFailed', { count: crawlStatus.enriched_failed }) }}</span>
      <span v-if="crawlPolling" class="inline-block h-3 w-3 rounded-full border-2 border-current border-t-transparent animate-spin" />
      <span v-if="crawlStatus.task_status === 'failed' && crawlStatus.error_msg" class="max-w-full truncate text-2xs monitor-status-error" :title="crawlStatus.error_msg">{{ crawlStatus.error_msg }}</span>
    </div>
  </div>
</template>
