<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import SpinnerLoader from '@/components/SpinnerLoader.vue'
const { t } = useI18n()
import {
  formatDate,
  formatTime,
  getStatusConfig,
  type SchedulerStatus,
  type Task,
} from '@/features/monitor/monitorViewModel'

defineProps<{
  isAdmin: boolean
  schedulerStatus: SchedulerStatus | null
  tasks: Task[]
  total: number
  page: number
  totalPages: number
  loading: boolean
}>()

const emit = defineEmits<{
  goPage: [page: number]
}>()
</script>

<template>
  <div class="grid grid-cols-1 gap-5 shrink-0" :class="isAdmin ? 'lg:grid-cols-3' : ''">
    <div v-if="isAdmin" class="stagger-enter glass-card flex flex-col p-5" style="animation-delay: 0.2s; max-height: 560px;">
      <h3 class="monitor-section-title mb-4 shrink-0 text-sm font-semibold">{{ t('monitor.scheduler') }}</h3>
      <div v-if="schedulerStatus" class="flex flex-col min-h-0 flex-1">
        <div class="mb-4 shrink-0 flex items-center gap-2.5">
          <span class="status-dot" :class="schedulerStatus.running ? 'monitor-status-dot-running animate-[pulseDot_2s_ease-in-out_infinite]' : 'monitor-status-dot-error'" />
          <span class="text-sm font-medium">{{ t(schedulerStatus.running ? 'monitor.running' : 'monitor.stopped') }}</span>
          <span class="ml-auto text-xs monitor-caption">{{ t('monitor.jobCount', { count: schedulerStatus.job_count }) }}</span>
        </div>
        <div class="space-y-2 overflow-y-auto">
          <div v-for="job in schedulerStatus.jobs" :key="job.id" class="monitor-surface-dim p-3">
            <p class="text-xs font-medium">{{ job.name }}</p>
            <p class="mt-1 text-2xs monitor-caption">{{ job.next_run_time ? t('monitor.nextRun', { date: formatDate(job.next_run_time) }) : t('monitor.unscheduled') }}</p>
          </div>
        </div>
      </div>
      <div v-else-if="loading" class="flex items-center gap-2 text-sm monitor-caption">
        <span class="inline-block h-4 w-4 rounded-full border-2 border-current border-t-transparent animate-spin" />{{ t('common.loading') }}
      </div>
    </div>

    <div class="stagger-enter glass-card overflow-hidden flex flex-col" :class="isAdmin ? 'lg:col-span-2' : 'lg:col-span-1'" style="animation-delay: 0.3s">
      <div class="monitor-divider flex items-center justify-between px-5 py-3.5 shrink-0 border-b">
        <h3 class="monitor-section-title text-sm font-semibold">{{ t('monitor.recentTasks') }}</h3>
        <span class="monitor-badge">{{ t('monitor.totalItems', { count: total }) }}</span>
      </div>

      <div class="overflow-x-auto flex-1">
        <table class="monitor-table">
          <thead>
            <tr>
              <th>ID</th>
              <th>{{ t('monitor.taskName') }}</th>
              <th>{{ t('monitor.status') }}</th>
              <th>{{ t('monitor.itemCount') }}</th>
              <th>{{ t('monitor.startedAt') }}</th>
              <th>{{ t('monitor.endedAt') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="loading && !tasks.length">
              <td colspan="6" class="px-4 py-6"><SpinnerLoader class="min-h-[72px]" :size="22" /></td>
            </tr>
            <tr v-else-if="!tasks.length">
              <td colspan="6" class="px-4 py-8 text-center text-sm monitor-caption">{{ t('monitor.noTasks') }}</td>
            </tr>
            <tr v-for="task in tasks" :key="task.id" :class="tasks.indexOf(task) % 2 !== 0 ? 'bg-even' : ''">
              <td class="whitespace-nowrap px-4 py-3 text-xs monitor-caption font-mono">#{{ task.id }}</td>
              <td class="px-4 py-3 text-xs font-medium max-w-[200px] truncate">{{ task.task_name }}</td>
              <td class="whitespace-nowrap px-4 py-3">
                <div class="flex flex-col gap-1">
                  <span class="badge" :class="[getStatusConfig(task.status).bg]">
                    <span class="status-dot shrink-0" :class="getStatusConfig(task.status).dot" />
                    {{ getStatusConfig(task.status).labelKey ? t(`monitor.${getStatusConfig(task.status).labelKey}`) : getStatusConfig(task.status).rawLabel }}
                  </span>
                  <span v-if="task.error_msg" class="max-w-[180px] truncate text-2xs monitor-status-error" :title="task.error_msg">{{ task.error_msg }}</span>
                </div>
              </td>
              <td class="whitespace-nowrap px-4 py-3 text-xs tabular-nums">{{ task.item_count }}</td>
              <td class="whitespace-nowrap px-4 py-3 text-xs monitor-caption">{{ formatDate(task.started_at) }}</td>
              <td class="whitespace-nowrap px-4 py-3 text-xs monitor-caption">
                <span v-if="task.finished_at">{{ formatTime(task.finished_at) }}</span>
                <span v-else class="monitor-caption">—</span>
              </td>
            </tr>
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
  </div>
</template>
