<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import SpinnerLoader from '@/components/SpinnerLoader.vue'
import type {
  GithubRetainedProject,
  GithubRetainedReason,
  GithubUnprocessableProject,
} from '@/features/monitor/monitorModel'

const props = withDefaults(defineProps<{
  items?: GithubUnprocessableProject[]
  total?: number
  page?: number
  totalPages?: number
  retainedItems?: GithubRetainedProject[]
  retainedTotal?: number
  retainedPage?: number
  retainedTotalPages?: number
  loading?: boolean
  error?: string
}>(), {
  items: () => [],
  total: 0,
  page: 1,
  totalPages: 1,
  retainedItems: () => [],
  retainedTotal: 0,
  retainedPage: 1,
  retainedTotalPages: 1,
  loading: false,
  error: '',
})

const emit = defineEmits<{
  'go-page': [page: number]
  'go-retained-page': [page: number]
}>()
const { t } = useI18n()

const pageWindow = (page: number, totalPages: number) => {
  const start = Math.max(1, page - 2)
  const end = Math.min(totalPages, page + 2)
  return Array.from({ length: end - start + 1 }, (_, index) => start + index)
}
const unprocessablePageTargets = computed(() => pageWindow(props.page, props.totalPages))
const retainedPageTargets = computed(() => pageWindow(props.retainedPage, props.retainedTotalPages))

// retained 原因的 i18n 键映射；后端新增原因时先落到 lost_input 文案，避免显示裸键
const RETAINED_REASON_KEYS: Record<GithubRetainedReason, string> = {
  not_found: 'monitor.enrichment.retainedReasonNotFound',
  snapshot_below_threshold: 'monitor.enrichment.retainedReasonSnapshotBelow',
  lost_input: 'monitor.enrichment.retainedReasonLostInput',
  tombstone: 'monitor.enrichment.retainedReasonTombstone',
}
</script>

<template>
  <div v-if="total > 0 || retainedTotal > 0 || loading || error" class="grid min-w-0 gap-5">
    <section
      v-if="total > 0 || (loading && retainedTotal <= 0) || (error && retainedTotal <= 0)"
      class="enrichment-project-card stagger-enter glass-card flex min-h-0 flex-col overflow-hidden"
      data-testid="unprocessable-project-card"
    >
      <div class="monitor-divider shrink-0 flex flex-wrap items-center justify-between gap-3 border-b px-5 py-4">
        <div>
          <h2 class="monitor-section-title">{{ t('monitor.enrichment.unprocessableTitle') }}</h2>
          <p class="monitor-caption">{{ t('monitor.enrichment.unprocessableHint') }}</p>
        </div>
        <span class="monitor-badge">{{ t('monitor.enrichment.unprocessableCount', { count: total }) }}</span>
      </div>
      <p v-if="error" class="monitor-status-error mx-5 mt-4 shrink-0 rounded border px-3 py-2" role="alert">
        {{ error }}
      </p>
      <div class="enrichment-project-table min-h-0 flex-1 overflow-auto">
        <table class="monitor-table min-w-full">
          <thead><tr>
            <th>{{ t('monitor.enrichment.unprocessableRepository') }}</th>
            <th>{{ t('monitor.enrichment.unprocessableStars') }}</th>
            <th>{{ t('monitor.enrichment.unprocessableReason') }}</th>
          </tr></thead>
          <tbody>
            <tr v-if="loading"><td colspan="3"><SpinnerLoader class="min-h-[72px]" :size="22" /></td></tr>
            <tr v-else-if="!items.length"><td colspan="3" class="text-center">{{ t('common.noData') }}</td></tr>
            <tr v-for="item in items" v-else :key="item.repo_id">
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
      <div class="monitor-divider shrink-0 flex flex-wrap items-center justify-between gap-3 border-t px-5 py-3">
        <span class="monitor-caption">{{ t('monitor.pageSummary', { page, totalPages, total }) }}</span>
        <div class="flex flex-wrap items-center gap-1">
          <button class="monitor-pagination-btn" :disabled="loading || page <= 1" @click="emit('go-page', page - 1)">{{ t('monitor.previous') }}</button>
          <button v-for="target in unprocessablePageTargets" :key="target" class="monitor-pagination-btn" :class="{ active: target === page }" :disabled="loading" @click="emit('go-page', target)">{{ target }}</button>
          <button class="monitor-pagination-btn" :disabled="loading || page >= totalPages" @click="emit('go-page', page + 1)">{{ t('monitor.next') }}</button>
        </div>
      </div>
    </section>

    <section
      v-if="retainedTotal > 0"
      class="enrichment-project-card stagger-enter glass-card flex min-h-0 flex-col overflow-hidden"
      data-testid="retained-project-card"
    >
      <div class="monitor-divider shrink-0 flex flex-wrap items-center justify-between gap-3 border-b px-5 py-4">
        <div>
          <h2 class="monitor-section-title">{{ t('monitor.enrichment.retainedTitle') }}</h2>
          <p class="monitor-caption">{{ t('monitor.enrichment.retainedHint') }}</p>
        </div>
        <span class="monitor-badge">{{ t('monitor.enrichment.retainedCount', { count: retainedTotal }) }}</span>
      </div>
      <p v-if="error" class="monitor-status-error mx-5 mt-4 shrink-0 rounded border px-3 py-2" role="alert">
        {{ error }}
      </p>
      <div class="enrichment-project-table min-h-0 flex-1 overflow-auto">
        <table class="monitor-table min-w-full">
          <thead><tr>
            <th>{{ t('monitor.enrichment.unprocessableRepository') }}</th>
            <th>{{ t('monitor.enrichment.unprocessableStars') }}</th>
            <th>{{ t('monitor.enrichment.unprocessableReason') }}</th>
          </tr></thead>
          <tbody>
            <tr v-if="loading"><td colspan="3"><SpinnerLoader class="min-h-[72px]" :size="22" /></td></tr>
            <tr v-else-if="!retainedItems.length"><td colspan="3" class="text-center">{{ t('common.noData') }}</td></tr>
            <tr v-for="item in retainedItems" v-else :key="`retained-${item.repo_id}`">
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
      <div class="monitor-divider shrink-0 flex flex-wrap items-center justify-between gap-3 border-t px-5 py-3">
        <span class="monitor-caption">{{ t('monitor.pageSummary', { page: retainedPage, totalPages: retainedTotalPages, total: retainedTotal }) }}</span>
        <div class="flex flex-wrap items-center gap-1">
          <button class="monitor-pagination-btn" :disabled="loading || retainedPage <= 1" @click="emit('go-retained-page', retainedPage - 1)">{{ t('monitor.previous') }}</button>
          <button v-for="target in retainedPageTargets" :key="target" class="monitor-pagination-btn" :class="{ active: target === retainedPage }" :disabled="loading" @click="emit('go-retained-page', target)">{{ target }}</button>
          <button class="monitor-pagination-btn" :disabled="loading || retainedPage >= retainedTotalPages" @click="emit('go-retained-page', retainedPage + 1)">{{ t('monitor.next') }}</button>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.enrichment-project-card {
  height: 560px;
}

.enrichment-project-table {
  overscroll-behavior: contain;
}

.enrichment-project-table :deep(thead) {
  position: sticky;
  top: 0;
  z-index: 1;
}
</style>
