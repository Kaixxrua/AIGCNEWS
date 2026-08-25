<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import type { GithubEnrichmentStatus } from '@/features/monitor/monitorModel'

const { t } = useI18n()

const props = defineProps<{
  status: GithubEnrichmentStatus | null
  loading: boolean
  retrying: boolean
  backfilling: boolean
  cancelling: boolean
  cancelWatching: boolean
  polling: boolean
  concurrency: number
  reasoningEffort: string
  effectiveReasoningEffort: string
  savingReasoningEffort: boolean
}>()

const emit = defineEmits<{
  refresh: []
  retry: []
  backfill: []
  cancel: []
  updateConcurrency: [value: number]
  updateReasoningEffort: [value: string]
}>()

// 推理强度草稿：失焦/回车才提交保存；保存成功后由父级回写归一值，本地随之同步
const effortDraft = ref(props.reasoningEffort)
watch(() => props.reasoningEffort, (value) => { effortDraft.value = value })
const commitReasoningEffort = () => emit('updateReasoningEffort', effortDraft.value)

const progress = computed(() => {
  const explicit = props.status?.catalog_progress
  const total = Math.max(
    Number(explicit?.total ?? props.status?.catalog_total ?? props.status?.eligible ?? 0),
    0,
  )
  const succeeded = Math.max(Number(explicit?.succeeded ?? props.status?.catalog_succeeded ?? props.status?.succeeded ?? 0), 0)
  const failed = Math.max(Number(explicit?.failed ?? props.status?.catalog_failed ?? props.status?.failed ?? 0), 0)
  const unprocessable = Math.max(Number(explicit?.unprocessable ?? props.status?.catalog_unprocessable ?? props.status?.unprocessable ?? 0), 0)
  const pending = Math.max(total - succeeded - failed - unprocessable, 0)
  return { total, succeeded, failed, unprocessable, pending }
})
const succeededPct = computed(() => (progress.value.total > 0 ? Math.min(progress.value.succeeded / progress.value.total * 100, 100) : 0))
const failedPct = computed(() => (progress.value.total > 0 ? Math.min(progress.value.failed / progress.value.total * 100, 100) : 0))
const unprocessablePct = computed(() => (progress.value.total > 0 ? Math.min(progress.value.unprocessable / progress.value.total * 100, 100) : 0))
const pendingPct = computed(() => (progress.value.total > 0 ? Math.min(progress.value.pending / progress.value.total * 100, 100) : 0))
const succeededPercent = computed(() => Math.round(succeededPct.value))

const retainedBuckets = computed(() => {
  const buckets = props.status?.retained_buckets ?? {}
  const definitions = [
    { key: 'not_found', label: 'monitor.enrichment.retainedNotFound' },
    { key: 'snapshot_below_threshold', label: 'monitor.enrichment.retainedBelowThreshold' },
    { key: 'lost_input', label: 'monitor.enrichment.retainedLostInput' },
    { key: 'tombstone', label: 'monitor.enrichment.retainedTombstone' },
  ] as const
  return definitions
    .map(({ key, label }) => ({ key, label, count: Math.max(Number(buckets[key] ?? 0), 0) }))
    .filter((bucket) => bucket.count > 0)
})
const retainedTotal = computed(() => Math.max(
  Number(props.status?.retained_total ?? retainedBuckets.value.reduce((sum, bucket) => sum + bucket.count, 0)),
  0,
))
</script>

<template>
  <div class="stagger-enter glass-card shrink-0 p-5" style="animation-delay: 0.2s">
    <div class="flex items-center gap-2 mb-3">
      <svg class="h-4 w-4 monitor-caption" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/><path d="M2 12l10 5 10-5"/></svg>
      <h3 class="monitor-section-title text-sm font-semibold">{{ t('monitor.enrichment.title') }}</h3>
      <span v-if="status && status.failed > 0" class="monitor-status-error flex items-center gap-1.5 px-2 py-0.5 rounded text-2xs font-bold tabular-nums">
        <span class="enrichment-alert-dot" />
        {{ t('monitor.enrichment.failed', { count: status.failed }) }}
      </span>
      <button class="monitor-btn-ghost ml-auto" :disabled="loading" @click="emit('refresh')">
        <svg class="h-3.5 w-3.5" :class="loading ? 'animate-spin' : ''" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 11-2.12-9.36L23 10"/></svg>
        {{ t('monitor.enrichment.refresh') }}
      </button>
    </div>

    <div v-if="status && progress.total > 0" class="mb-3">
      <div class="flex items-center justify-between text-2xs monitor-caption mb-1">
        <span>{{ t('monitor.enrichment.progress') }}</span>
        <span class="tabular-nums font-bold">{{ succeededPercent }}%</span>
        <span class="sr-only">{{ progress.succeeded }} succeeded, {{ progress.failed }} failed, {{ progress.unprocessable }} unprocessable, {{ progress.pending }} pending</span>
      </div>
      <div
        class="enrichment-progress"
        role="progressbar"
        :aria-valuenow="succeededPercent"
        aria-valuemin="0"
        aria-valuemax="100"
        :aria-label="t('monitor.enrichment.progress')"
      >
        <div class="enrichment-progress-succeeded" :style="{ width: `${succeededPct}%` }" />
        <div class="enrichment-progress-failed" :style="{ width: `${failedPct}%` }" />
        <div class="enrichment-progress-unprocessable" :style="{ width: `${unprocessablePct}%` }" />
        <div class="enrichment-progress-pending" :style="{ width: `${pendingPct}%` }" />
      </div>
      <p v-if="polling" class="mt-1.5 flex items-center gap-1.5 text-2xs monitor-caption">
        <span class="enrichment-polling-spinner" />
        {{ t('monitor.enrichment.running') }}
      </p>
    </div>

    <div class="flex flex-wrap items-center gap-x-4 gap-y-3">
      <template v-if="status">
        <span class="text-xs monitor-caption tabular-nums">{{ t('monitor.enrichment.enriched', { done: progress.succeeded, total: progress.total }) }}</span>
        <span class="text-xs monitor-caption tabular-nums">{{ progress.failed }} failed · {{ progress.unprocessable }} unprocessable · {{ progress.pending }} pending</span>
        <span v-if="retainedTotal > 0" class="text-xs monitor-caption tabular-nums">
          {{ t('monitor.enrichment.retainedSummary', { count: retainedTotal }) }}
          <span class="inline-flex flex-wrap gap-1.5 ml-1.5">
            <span
              v-for="bucket in retainedBuckets"
              :key="bucket.key"
              class="enrichment-retained-chip rounded px-1.5 py-0.5"
            >{{ t(bucket.label) }} {{ bucket.count }}</span>
          </span>
        </span>
        <span v-if="status.github_library_total != null" class="text-xs monitor-caption tabular-nums">
          {{ t('monitor.enrichment.libraryTotal', { count: status.github_library_total }) }}
        </span>
        <span v-if="status.content_total != null" class="text-xs monitor-caption tabular-nums">
          {{ t('monitor.enrichment.contentTotal', { count: status.content_total }) }}
        </span>
        <span class="text-xs monitor-caption tabular-nums">{{ t('monitor.enrichment.pending', { count: progress.pending }) }}</span>
        <span v-if="status.failed > 0" class="text-xs monitor-status-error tabular-nums">{{ t('monitor.enrichment.failed', { count: status.failed }) }}</span>
      </template>
      <span v-else class="text-xs monitor-caption">{{ t(loading ? 'common.refreshing' : 'monitor.enrichment.empty') }}</span>

      <button
        class="monitor-btn-secondary relative"
        :disabled="retrying || backfilling || cancelling || cancelWatching || polling || status?.running || !status || (status.queue_failed ?? status.failed) <= 0"
        :title="t('monitor.enrichment.retryTitle')"
        @click="emit('retry')"
      >
        <svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 102.13-9.36L1 10"/></svg>
        {{ t(retrying ? 'monitor.enrichment.retrying' : 'monitor.enrichment.retry') }}
        <span v-if="status && status.failed > 0" class="enrichment-alert-dot enrichment-alert-dot--button" />
      </button>

      <button
        class="monitor-btn-primary"
        :disabled="backfilling || retrying || cancelling || cancelWatching || polling || status?.running || !status || (status.queue_pending ?? status.pending) <= 0"
        :title="t('monitor.enrichment.backfillTitle')"
        @click="emit('backfill')"
      >
        <svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"/></svg>
        {{ t(backfilling ? 'monitor.enrichment.retrying' : 'monitor.enrichment.backfill') }}
      </button>

      <label class="inline-flex items-center gap-1.5 text-xs monitor-caption" :title="t('monitor.enrichment.concurrencyHint')">
        {{ t('monitor.enrichment.concurrency') }}
        <input
          :value="concurrency"
          type="number"
          min="1"
          max="10"
          step="1"
          class="input w-16 py-1.5 text-xs"
          :disabled="retrying || backfilling || cancelling || polling"
          @input="emit('updateConcurrency', Number(($event.target as HTMLInputElement).value))"
        />
      </label>

      <label class="inline-flex items-center gap-1.5 text-xs monitor-caption" :title="t('monitor.enrichment.reasoningEffortHint')">
        {{ t('monitor.enrichment.reasoningEffort') }}
        <input
          v-model="effortDraft"
          type="text"
          :placeholder="t('monitor.enrichment.reasoningEffortPlaceholder')"
          autocomplete="off"
          class="input w-32 py-1.5 text-xs"
          :disabled="savingReasoningEffort"
          @change="commitReasoningEffort"
          @keyup.enter="commitReasoningEffort"
        />
        <span v-if="effectiveReasoningEffort" class="text-2xs monitor-caption tabular-nums">
          {{ t('monitor.enrichment.reasoningEffortEffective', { effort: effectiveReasoningEffort }) }}
        </span>
      </label>

      <!-- 有批次运行时出现：本地轮询中，或服务端 running 标记（刷新页面后仍可终止）；
           终止观望期（等待服务端 running 清零）保持锁定，批次结束才消失 -->
      <button
        v-if="polling || status?.running || cancelWatching"
        class="monitor-btn-secondary enrichment-cancel-btn"
        :disabled="cancelling || cancelWatching"
        :title="t('monitor.enrichment.cancelTitle')"
        @click="emit('cancel')"
      >
        <svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="currentColor" stroke="currentColor" stroke-width="1"><rect x="6" y="6" width="12" height="12" rx="1.5"/></svg>
        {{ t(cancelling || cancelWatching ? 'monitor.enrichment.cancelling' : 'monitor.enrichment.cancel') }}
      </button>
    </div>

    <p class="mt-3 text-2xs monitor-caption">{{ t('monitor.enrichment.hint') }}</p>
  </div>
</template>

<style scoped>
.enrichment-cancel-btn {
  color: var(--error-accent);
}

.enrichment-alert-dot {
  display: inline-block;
  width: 7px;
  height: 7px;
  border-radius: 9999px;
  background: var(--error-accent);
  flex-shrink: 0;
}

.enrichment-alert-dot--button {
  position: absolute;
  top: -3px;
  right: -3px;
  width: 9px;
  height: 9px;
  border: 1.5px solid var(--projects-paper-light);
  animation: enrichment-dot-pulse 1.6s ease-in-out infinite;
}

@keyframes enrichment-dot-pulse {
  0%, 100% { transform: scale(1); opacity: 1; }
  50% { transform: scale(1.35); opacity: 0.65; }
}

.enrichment-progress {
  display: flex;
  height: 10px;
  overflow: hidden;
  border: 1px solid var(--projects-accent);
  border-radius: 4px;
  background: var(--paper-muted);
  box-shadow: 2px 2px 0 var(--shadow-hard);
}

.enrichment-progress-succeeded {
  background: var(--success-ink);
  transition: width 0.4s ease;
}

.enrichment-progress-failed {
  background: var(--error-accent);
  transition: width 0.4s ease;
}

.enrichment-progress-unprocessable {
  background: #9ca3af;
  transition: width 0.4s ease;
}

.enrichment-progress-pending {
  background: repeating-linear-gradient(135deg, #d6d3d1 0 4px, #e7e5e4 4px 8px);
  transition: width 0.4s ease;
}

.enrichment-polling-spinner {
  display: inline-block;
  width: 10px;
  height: 10px;
  border: 2px solid currentColor;
  border-top-color: transparent;
  border-radius: 9999px;
  animation: enrichment-spin 0.8s linear infinite;
}

@keyframes enrichment-spin {
  to { transform: rotate(360deg); }
}

@media (prefers-reduced-motion: reduce) {
  .enrichment-alert-dot--button,
  .enrichment-polling-spinner {
    animation: none;
  }
  .enrichment-progress-succeeded,
  .enrichment-progress-failed,
  .enrichment-progress-unprocessable,
  .enrichment-progress-pending {
    transition: none;
  }
}
</style>
