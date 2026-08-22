<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import type { GithubEnrichmentStatus, GithubRetainedReason } from '@/features/monitor/monitorModel'

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

const eligible = computed(() => props.status?.eligible ?? 0)
const retainedTotal = computed(() => props.status?.retained_total ?? 0)
// 进度条分母 = 可执行队列 eligible + 在库保留 retainedTotal：
// 保留段以灰色补齐在条上，直观对齐项目库总数（eligible + retained = 库内富化成功全集）。
// 队列完成度标签仍按 succeeded/eligible 计，灰色段不参与完成率。
const barTotal = computed(() => eligible.value + retainedTotal.value)
const succeededPct = computed(() => (barTotal.value > 0 ? ((props.status?.succeeded ?? 0) / barTotal.value) * 100 : 0))
const failedPct = computed(() => (barTotal.value > 0 ? ((props.status?.failed ?? 0) / barTotal.value) * 100 : 0))
const retainedPct = computed(() => (barTotal.value > 0 ? (retainedTotal.value / barTotal.value) * 100 : 0))
const succeededPercent = computed(() =>
  eligible.value > 0 ? Math.round(((props.status?.succeeded ?? 0) / eligible.value) * 100) : 0,
)

// 在库但已退出可执行队列的项目：单独成组展示，不并入进度分母；
// 分桶顺序按可溯源优先级（下架 → 星数回落 → 简介被删 → 改名旧名）。
const RETAINED_BUCKET_ORDER: GithubRetainedReason[] = [
  'not_found',
  'snapshot_below_threshold',
  'lost_input',
  'tombstone',
]
const RETAINED_BUCKET_I18N: Record<GithubRetainedReason, string> = {
  not_found: 'monitor.enrichment.retainedBucketNotFound',
  snapshot_below_threshold: 'monitor.enrichment.retainedBucketSnapshotBelow',
  lost_input: 'monitor.enrichment.retainedBucketLostInput',
  tombstone: 'monitor.enrichment.retainedBucketTombstone',
}
const retainedChips = computed(() => {
  const buckets = props.status?.retained_buckets ?? {}
  return RETAINED_BUCKET_ORDER
    .map((reason) => ({ reason, count: buckets[reason] ?? 0 }))
    .filter((chip) => chip.count > 0)
})
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

    <div v-if="status && barTotal > 0" class="mb-3">
      <div class="flex items-center justify-between text-2xs monitor-caption mb-1">
        <span>{{ t('monitor.enrichment.progress') }}</span>
        <span class="tabular-nums font-bold">{{ succeededPercent }}%</span>
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
        <!-- 在库保留段：margin-left:auto 跳过待处理间隙钉在条尾，
             灰色标注与项目库总数的差额 -->
        <div
          v-if="retainedTotal > 0"
          class="enrichment-progress-retained"
          :style="{ width: `${retainedPct}%` }"
          :title="t('monitor.enrichment.retainedBarTooltip', { count: retainedTotal })"
        />
      </div>
      <p v-if="polling" class="mt-1.5 flex items-center gap-1.5 text-2xs monitor-caption">
        <span class="enrichment-polling-spinner" />
        {{ t('monitor.enrichment.running') }}
      </p>
    </div>

    <div class="flex flex-wrap items-center gap-x-4 gap-y-3">
      <template v-if="status">
        <span class="text-xs monitor-caption tabular-nums">{{ t('monitor.enrichment.enriched', { done: status.succeeded, total: status.eligible }) }}</span>
        <span class="text-xs monitor-caption tabular-nums">{{ t('monitor.enrichment.pending', { count: status.pending }) }}</span>
        <span v-if="status.failed > 0" class="text-xs monitor-status-error tabular-nums">{{ t('monitor.enrichment.failed', { count: status.failed }) }}</span>
      </template>
      <span v-else class="text-xs monitor-caption">{{ t(loading ? 'common.refreshing' : 'monitor.enrichment.empty') }}</span>

      <button
        class="monitor-btn-secondary relative"
        :disabled="retrying || backfilling || cancelling || cancelWatching || polling || !status || status.failed <= 0"
        :title="t('monitor.enrichment.retryTitle')"
        @click="emit('retry')"
      >
        <svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 102.13-9.36L1 10"/></svg>
        {{ t(retrying ? 'monitor.enrichment.retrying' : 'monitor.enrichment.retry') }}
        <span v-if="status && status.failed > 0" class="enrichment-alert-dot enrichment-alert-dot--button" />
      </button>

      <button
        class="monitor-btn-primary"
        :disabled="backfilling || retrying || cancelling || cancelWatching || polling || !status || status.pending <= 0"
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

    <p v-if="status && retainedTotal > 0" class="mt-2 text-2xs monitor-caption tabular-nums">
      <span class="enrichment-retained-swatch" aria-hidden="true" />
      {{ t('monitor.enrichment.retainedLead', { count: retainedTotal }) }}
      <span v-for="chip in retainedChips" :key="chip.reason" class="enrichment-retained-chip">
        {{ t(RETAINED_BUCKET_I18N[chip.reason], { count: chip.count }) }}
      </span>
    </p>

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

/* 在库保留段：灰色标注与项目库总数的差额；margin-left:auto 使其越过
   待处理间隙钉在条尾，队列 100% 完成时与绿色段相接 */
.enrichment-progress-retained {
  margin-left: auto;
  background: var(--ink-faint);
  transition: width 0.4s ease;
}

.enrichment-retained-swatch {
  display: inline-block;
  width: 10px;
  height: 8px;
  margin-right: 2px;
  border-radius: 2px;
  background: var(--ink-faint);
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

.enrichment-retained-chip {
  display: inline-block;
  margin-left: 4px;
  padding: 0 6px;
  border: 1px solid var(--projects-accent);
  border-radius: 4px;
  background: var(--paper-muted);
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
  .enrichment-progress-retained {
    transition: none;
  }
}
</style>
