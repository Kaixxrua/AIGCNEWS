<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import type {
  GithubRetainedProject,
  GithubRetainedReason,
  GithubUnprocessableProject,
} from '@/features/monitor/monitorModel'

withDefaults(defineProps<{
  items?: GithubUnprocessableProject[]
  total?: number
  retainedItems?: GithubRetainedProject[]
  retainedTotal?: number
}>(), {
  items: () => [],
  total: 0,
  retainedItems: () => [],
  retainedTotal: 0,
})

const { t } = useI18n()

// retained 原因的 i18n 键映射；后端新增原因时先落到空串键，由文案补齐
const RETAINED_REASON_KEYS: Record<GithubRetainedReason, string> = {
  not_found: 'monitor.enrichment.retainedReasonNotFound',
  snapshot_below_threshold: 'monitor.enrichment.retainedReasonSnapshotBelow',
  lost_input: 'monitor.enrichment.retainedReasonLostInput',
  tombstone: 'monitor.enrichment.retainedReasonTombstone',
}
</script>

<template>
  <section v-if="total > 0 || retainedTotal > 0" class="stagger-enter glass-card overflow-hidden">
    <template v-if="total > 0">
      <div class="monitor-divider flex flex-wrap items-center justify-between gap-3 border-b px-5 py-4">
        <div>
          <h2 class="monitor-section-title">{{ t('monitor.enrichment.unprocessableTitle') }}</h2>
          <p class="monitor-caption">{{ t('monitor.enrichment.unprocessableHint') }}</p>
        </div>
        <span class="monitor-badge">{{ t('monitor.enrichment.unprocessableCount', { count: total }) }}</span>
      </div>
      <div class="overflow-x-auto">
        <table class="monitor-table">
          <thead><tr>
            <th>{{ t('monitor.enrichment.unprocessableRepository') }}</th>
            <th>{{ t('monitor.enrichment.unprocessableStars') }}</th>
            <th>{{ t('monitor.enrichment.unprocessableReason') }}</th>
          </tr></thead>
          <tbody>
            <tr v-for="item in items" :key="item.repo_id">
              <td>
                <a
                  class="font-medium underline decoration-dotted underline-offset-2"
                  :href="item.url"
                  target="_blank"
                  rel="noopener noreferrer"
                >{{ item.full_name }}</a>
              </td>
              <td class="tabular-nums">{{ item.stars.toLocaleString() }}</td>
              <td>{{ t(`monitor.enrichment.unprocessableReason${item.reason === 'missing_description' ? 'MissingDescription' : ''}`) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>

    <template v-if="retainedTotal > 0">
      <div class="monitor-divider flex flex-wrap items-center justify-between gap-3 border-b px-5 py-4">
        <div>
          <h2 class="monitor-section-title">{{ t('monitor.enrichment.retainedTitle') }}</h2>
          <p class="monitor-caption">{{ t('monitor.enrichment.retainedHint') }}</p>
        </div>
        <span class="monitor-badge">{{ t('monitor.enrichment.retainedCount', { count: retainedTotal }) }}</span>
      </div>
      <div class="overflow-x-auto">
        <table class="monitor-table">
          <thead><tr>
            <th>{{ t('monitor.enrichment.unprocessableRepository') }}</th>
            <th>{{ t('monitor.enrichment.unprocessableStars') }}</th>
            <th>{{ t('monitor.enrichment.unprocessableReason') }}</th>
          </tr></thead>
          <tbody>
            <tr v-for="item in retainedItems" :key="`retained-${item.repo_id}`">
              <td>
                <a
                  class="font-medium underline decoration-dotted underline-offset-2"
                  :href="item.url"
                  target="_blank"
                  rel="noopener noreferrer"
                >{{ item.full_name }}</a>
              </td>
              <td class="tabular-nums">{{ item.stars.toLocaleString() }}</td>
              <td>{{ t(RETAINED_REASON_KEYS[item.reason] ?? 'monitor.enrichment.retainedReasonLostInput') }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>
  </section>
</template>
