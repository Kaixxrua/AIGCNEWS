<script setup lang="ts">
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import SpinnerLoader from '@/components/SpinnerLoader.vue'
import { formatDate, type ErrorLogEntry } from '@/features/monitor/monitorViewModel'

const props = defineProps<{
  errorLogs: ErrorLogEntry[]
  total: number
  page: number
  totalPages: number
  loading: boolean
}>()

const emit = defineEmits<{
  goPage: [page: number]
}>()

const { t } = useI18n()

// 展开堆栈为组件自持的纯展示状态（哑组件约定，同 MonitorSectionNav 的折叠集）
const expandedIds = ref<ReadonlySet<number>>(new Set())
const toggleStack = (id: number) => {
  const next = new Set(expandedIds.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  expandedIds.value = next
}

// ERROR/CRITICAL 红，其余级别中性色
const levelBadgeClass = (level: string) =>
  ['error', 'critical', 'fatal'].includes((level || '').toLowerCase())
    ? 'monitor-status-error'
    : 'monitor-status-unknown'
</script>

<template>
  <div class="stagger-enter glass-card overflow-hidden flex flex-col" style="animation-delay: 0.2s">
    <div class="monitor-divider flex items-center justify-between px-5 py-3.5 shrink-0 border-b">
      <div>
        <h3 class="monitor-section-title text-sm font-semibold">{{ t('monitor.errorLog.title') }}</h3>
        <p class="mt-0.5 text-2xs monitor-caption">{{ t('monitor.errorLog.hint') }}</p>
      </div>
      <span class="monitor-badge shrink-0">{{ t('monitor.totalItems', { count: total }) }}</span>
    </div>

    <div class="overflow-x-auto flex-1">
      <table class="monitor-table">
        <thead>
          <tr>
            <th>{{ t('monitor.errorLog.time') }}</th>
            <th>{{ t('monitor.errorLog.level') }}</th>
            <th>{{ t('monitor.errorLog.logger') }}</th>
            <th>{{ t('monitor.errorLog.message') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="loading && !errorLogs.length">
            <td colspan="4" class="px-4 py-6"><SpinnerLoader class="min-h-[72px]" :size="22" /></td>
          </tr>
          <tr v-else-if="!errorLogs.length">
            <td colspan="4" class="px-4 py-8 text-center text-sm monitor-caption">{{ t('monitor.errorLog.empty') }}</td>
          </tr>
          <template v-for="entry in props.errorLogs" :key="entry.id">
            <tr
              :class="[
                props.errorLogs.indexOf(entry) % 2 !== 0 ? 'bg-even' : '',
                entry.stack_trace ? 'cursor-pointer' : '',
              ]"
              :aria-expanded="entry.stack_trace ? expandedIds.has(entry.id) : undefined"
              @click="entry.stack_trace ? toggleStack(entry.id) : undefined"
            >
              <td class="whitespace-nowrap px-4 py-3 text-xs monitor-caption">{{ formatDate(entry.occurred_at) }}</td>
              <td class="whitespace-nowrap px-4 py-3">
                <span class="badge" :class="levelBadgeClass(entry.level)">{{ entry.level }}</span>
              </td>
              <td class="px-4 py-3 text-xs monitor-caption font-mono max-w-[220px] truncate" :title="entry.logger_name">{{ entry.logger_name }}</td>
              <td class="px-4 py-3 text-xs max-w-[420px]">
                <div class="flex items-start gap-1.5">
                  <svg v-if="entry.stack_trace" class="mt-0.5 h-3 w-3 shrink-0 transition-transform" :class="{ 'rotate-90': expandedIds.has(entry.id) }" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="9 18 15 12 9 6"/></svg>
                  <span class="break-all">
                    <span v-if="entry.exception_type" class="font-medium">{{ entry.exception_type }}: </span>{{ entry.message }}
                  </span>
                </div>
              </td>
            </tr>
            <tr v-if="entry.stack_trace && expandedIds.has(entry.id)">
              <td colspan="4" class="px-4 py-3">
                <pre class="monitor-surface-dim max-h-72 overflow-auto whitespace-pre-wrap break-all p-3 text-2xs font-mono">{{ entry.stack_trace }}</pre>
              </td>
            </tr>
          </template>
        </tbody>
      </table>
    </div>

    <div class="monitor-divider flex items-center justify-between px-5 py-3 shrink-0 border-t">
      <p class="text-xs monitor-caption">{{ t('monitor.pageSummary', { page, totalPages, total }) }}</p>
      <div class="flex items-center gap-1">
        <button class="monitor-pagination-btn" :disabled="page <= 1" @click="emit('goPage', 1)">«</button>
        <button class="monitor-pagination-btn" :disabled="page <= 1" @click="emit('goPage', page - 1)">{{ t('monitor.previous') }}</button>
        <template v-for="targetPage in totalPages" :key="targetPage">
          <button v-if="Math.abs(targetPage - page) <= 2" class="monitor-pagination-btn" :class="{ active: targetPage === page }" @click="emit('goPage', targetPage)">{{ targetPage }}</button>
        </template>
        <button class="monitor-pagination-btn" :disabled="page >= totalPages" @click="emit('goPage', page + 1)">{{ t('monitor.next') }}</button>
        <button class="monitor-pagination-btn" :disabled="page >= totalPages" @click="emit('goPage', totalPages)">»</button>
      </div>
    </div>
  </div>
</template>
