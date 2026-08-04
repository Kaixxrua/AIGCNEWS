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
    <div class="flex items-center justify-between px-5 py-3.5 shrink-0" style="border-bottom: 1px solid rgba(168,162,158,0.15)">
      <div>
        <h3 class="text-sm font-semibold text-stone-700">{{ t('monitor.mcpToolCalls') }}</h3>
        <p class="mt-0.5 text-2xs text-stone-400">
          {{ t('monitor.mcpToolCallsHint') }}<span v-if="snapshot?.since"> · {{ t('monitor.mcpToolCallsSince', { date: formatDate(snapshot.since) }) }}</span>
        </p>
      </div>
      <span class="badge bg-white text-stone-500 border border-stone-200">{{ t('monitor.mcpToolCallsTotal', { count: snapshot?.total_calls ?? 0 }) }}</span>
    </div>

    <div class="overflow-x-auto">
      <table class="min-w-full">
        <thead>
          <tr style="border-bottom: 1px solid rgba(168,162,158,0.15); background: rgba(250,250,249,0.5)">
            <th class="px-4 py-2.5 text-left text-2xs font-semibold uppercase tracking-wider text-stone-400">{{ t('monitor.toolName') }}</th>
            <th class="px-4 py-2.5 text-left text-2xs font-semibold uppercase tracking-wider text-stone-400">{{ t('monitor.callCount') }}</th>
            <th class="px-4 py-2.5 text-left text-2xs font-semibold uppercase tracking-wider text-stone-400">{{ t('monitor.lastCalledAt') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="loading && !rows.length">
            <td colspan="3" class="px-4 py-8 text-center text-sm text-stone-400"><span class="inline-block h-5 w-5 rounded-full border-2 border-stone-200 border-t-stone-500 animate-spin" /></td>
          </tr>
          <tr v-else-if="!rows.length"><td colspan="3" class="px-4 py-8 text-center text-sm text-stone-400">{{ t('monitor.noToolCalls') }}</td></tr>
          <tr v-for="(row, index) in rows" :key="row.name" class="transition-colors hover:bg-stone-50/50" :style="index % 2 !== 0 ? 'background: rgba(250,250,249,0.4)' : ''">
            <td class="px-4 py-3 text-xs font-medium text-stone-700 font-mono">{{ row.name }}</td>
            <td class="whitespace-nowrap px-4 py-3 text-xs text-stone-500 tabular-nums">{{ row.calls }}</td>
            <td class="whitespace-nowrap px-4 py-3 text-xs text-stone-400">{{ formatDate(row.lastCalledAt) }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
