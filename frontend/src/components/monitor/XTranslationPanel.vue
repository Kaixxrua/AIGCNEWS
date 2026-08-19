<script setup lang="ts">
import type { XTranslationStatus } from '@/features/monitor/monitorModel'

const props = defineProps<{
  status: XTranslationStatus | null
  loading: boolean
  retrying: boolean
}>()

defineEmits<{ refresh: []; retry: [] }>()
</script>

<template>
  <section class="glass-card p-5" aria-labelledby="x-translation-heading">
    <div class="flex flex-wrap items-start justify-between gap-3">
      <div>
        <h2 id="x-translation-heading" class="text-base font-semibold">{{ $t('monitor.xTranslation.title') }}</h2>
        <p class="monitor-caption mt-1 text-sm">{{ $t('monitor.xTranslation.description') }}</p>
      </div>
      <div class="flex gap-2">
        <button class="monitor-btn-secondary" :disabled="loading" @click="$emit('refresh')">
          {{ $t('common.refresh') }}
        </button>
        <button
          class="monitor-btn-primary"
          :disabled="retrying || !props.status?.retryable"
          @click="$emit('retry')"
        >
          {{ $t(retrying ? 'monitor.xTranslation.running' : 'monitor.xTranslation.retry') }}
        </button>
      </div>
    </div>

    <div class="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-5">
      <div v-for="item in [
        ['succeeded', status?.succeeded || 0],
        ['pending', status?.pending || 0],
        ['failed', status?.failed || 0],
        ['runningCount', status?.running || 0],
        ['skipped', status?.skipped || 0],
      ]" :key="String(item[0])" class="rounded-xl border border-white/10 px-3 py-2">
        <div class="monitor-caption text-xs">{{ $t(`monitor.xTranslation.${item[0]}`) }}</div>
        <div class="mt-1 text-lg font-semibold tabular-nums">{{ item[1] }}</div>
      </div>
    </div>

    <div v-if="status?.latest_failure_model_name" class="monitor-caption mt-3 text-xs">
      {{ $t('monitor.xTranslation.model') }}:
      {{ status.latest_failure_model_provider }} / {{ status.latest_failure_model_name }}
    </div>
    <div v-if="status?.latest_failure_error" class="monitor-alert-error mt-3 rounded-xl px-3 py-2 text-xs">
      {{ status.latest_failure_error }}
    </div>
  </section>
</template>
