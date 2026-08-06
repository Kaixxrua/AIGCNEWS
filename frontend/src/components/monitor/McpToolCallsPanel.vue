<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  formatDate,
  toMcpToolCallRows,
  type McpToolCallMetricsSnapshot,
} from '@/features/monitor/monitorViewModel'

const props = defineProps<{
  snapshot: McpToolCallMetricsSnapshot | null
  loading: boolean
}>()

const { t } = useI18n()
const rows = computed(() => toMcpToolCallRows(props.snapshot))
</script>

<template>
  <div class="stagger-enter glass-card overflow-hidden flex flex-col shrink-0" style="animation-delay: 0.25s">
    <div class="monitor-divider flex items-center justify-between px-5 py-3.5 shrink-0 border-b">
      <div>
        <h3 class="monitor-section-title text-sm font-semibold">{{ t('monitor.mcpToolCalls') }}</h3>
        <p class="mt-0.5 text-2xs monitor-caption">
          {{ t('monitor.mcpToolCallsHint') }}<span v-if="snapshot?.since"> · {{ t('monitor.mcpToolCallsSince', { date: formatDate(snapshot.since) }) }}</span>
        </p>
      </div>
      <span class="monitor-badge">{{ t('monitor.mcpToolCallsTotal', { count: snapshot?.total_calls ?? 0 }) }}</span>
    </div>

    <div class="overflow-x-auto">
      <table class="monitor-table">
        <thead>
          <tr>
            <th>{{ t('monitor.toolName') }}</th>
            <th>{{ t('monitor.callCount') }}</th>
            <th>{{ t('monitor.lastCalledAt') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="loading && !rows.length">
            <td colspan="3" class="px-4 py-8 text-center text-sm monitor-caption">
              <span class="inline-block h-5 w-5 rounded-full border-2 border-current border-t-transparent animate-spin" />
            </td>
          </tr>
          <tr v-else-if="!rows.length">
            <td colspan="3" class="px-4 py-8 text-center text-sm monitor-caption">{{ t('monitor.noToolCalls') }}</td>
          </tr>
          <tr v-for="(row, index) in rows" :key="row.name" :class="index % 2 !== 0 ? 'bg-even' : ''">
            <td class="px-4 py-3 text-xs font-medium font-mono">{{ row.name }}</td>
            <td class="whitespace-nowrap px-4 py-3 text-xs tabular-nums">{{ row.calls }}</td>
            <td class="whitespace-nowrap px-4 py-3 text-xs monitor-caption">{{ formatDate(row.lastCalledAt) }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
