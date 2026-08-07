<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import type { GithubEnrichmentStatus } from '@/features/monitor/monitorModel'

const { t } = useI18n()

defineProps<{
  status: GithubEnrichmentStatus | null
  loading: boolean
  retrying: boolean
}>()

const emit = defineEmits<{
  refresh: []
  retry: []
}>()
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

    <div class="flex flex-wrap items-center gap-x-4 gap-y-3">
      <template v-if="status">
        <span class="text-xs monitor-caption tabular-nums">{{ t('monitor.enrichment.enriched', { done: status.succeeded, total: status.eligible }) }}</span>
        <span class="text-xs monitor-caption tabular-nums">{{ t('monitor.enrichment.pending', { count: status.pending }) }}</span>
        <span v-if="status.failed > 0" class="text-xs monitor-status-error tabular-nums">{{ t('monitor.enrichment.failed', { count: status.failed }) }}</span>
      </template>
      <span v-else class="text-xs monitor-caption">{{ t(loading ? 'common.refreshing' : 'monitor.enrichment.empty') }}</span>

      <button
        class="monitor-btn-secondary relative"
        :disabled="retrying || !status || status.failed <= 0"
        :title="t('monitor.enrichment.retryTitle')"
        @click="emit('retry')"
      >
        <svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 102.13-9.36L1 10"/></svg>
        {{ t(retrying ? 'monitor.enrichment.retrying' : 'monitor.enrichment.retry') }}
        <span v-if="status && status.failed > 0" class="enrichment-alert-dot enrichment-alert-dot--button" />
      </button>
    </div>

    <p class="mt-3 text-2xs monitor-caption">{{ t('monitor.enrichment.hint') }}</p>
  </div>
</template>

<style scoped>
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

@media (prefers-reduced-motion: reduce) {
  .enrichment-alert-dot--button {
    animation: none;
  }
}
</style>
