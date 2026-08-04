<script setup lang="ts">
import { useI18n } from 'vue-i18n'
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
      <h3 class="mb-4 shrink-0 text-sm font-semibold text-stone-700">{{ t('monitor.scheduler') }}</h3>
      <div v-if="schedulerStatus" class="flex flex-col min-h-0 flex-1">
        <div class="mb-4 shrink-0 flex items-center gap-2.5">
          <span class="status-dot" :class="schedulerStatus.running ? 'bg-brand-green animate-[pulseDot_2s_ease-in-out_infinite]' : 'bg-brand-rose'" />
          <span class="text-sm font-medium text-stone-700">{{ t(schedulerStatus.running ? 'monitor.running' : 'monitor.stopped') }}</span>
          <span class="ml-auto text-xs text-stone-400">{{ t('monitor.jobCount', { count: schedulerStatus.job_count }) }}</span>
        </div>
        <div class="space-y-2 overflow-y-auto">
          <div v-for="job in schedulerStatus.jobs" :key="job.id" class="rounded-2xl p-3" style="background: rgb(var(--card-rgb) / 0.6); border: 1px solid rgb(var(--stone-400-rgb) / 0.15)">
            <p class="text-xs font-medium text-stone-600">{{ job.name }}</p>
            <p class="mt-1 text-2xs text-stone-400">{{ job.next_run_time ? t('monitor.nextRun', { date: formatDate(job.next_run_time) }) : t('monitor.unscheduled') }}</p>
          </div>
        </div>
      </div>
      <div v-else-if="loading" class="flex items-center gap-2 text-sm text-stone-400">
        <span class="inline-block h-4 w-4 rounded-full border-2 border-stone-200 border-t-stone-500 animate-spin" />{{ t('common.loading') }}
      </div>
    </div>

    <div class="stagger-enter glass-card overflow-hidden flex flex-col" :class="isAdmin ? 'lg:col-span-2' : 'lg:col-span-1'" style="animation-delay: 0.3s">
      <div class="flex items-center justify-between px-5 py-3.5 shrink-0" style="border-bottom: 1px solid rgb(var(--stone-400-rgb) / 0.15)">
        <h3 class="text-sm font-semibold text-stone-700">{{ t('monitor.recentTasks') }}</h3>
        <span class="badge bg-card text-stone-500 border border-stone-200">{{ t('monitor.totalItems', { count: total }) }}</span>
      </div>

      <div class="overflow-x-auto flex-1">
        <table class="min-w-full">
          <thead>
            <tr style="border-bottom: 1px solid rgb(var(--stone-400-rgb) / 0.15); background: rgb(var(--stone-50-rgb) / 0.5)">
              <th class="px-4 py-2.5 text-left text-2xs font-semibold uppercase tracking-wider text-stone-400">ID</th>
              <th class="px-4 py-2.5 text-left text-2xs font-semibold uppercase tracking-wider text-stone-400">{{ t('monitor.taskName') }}</th>
              <th class="px-4 py-2.5 text-left text-2xs font-semibold uppercase tracking-wider text-stone-400">{{ t('monitor.status') }}</th>
              <th class="px-4 py-2.5 text-left text-2xs font-semibold uppercase tracking-wider text-stone-400">{{ t('monitor.itemCount') }}</th>
              <th class="px-4 py-2.5 text-left text-2xs font-semibold uppercase tracking-wider text-stone-400">{{ t('monitor.startedAt') }}</th>
              <th class="px-4 py-2.5 text-left text-2xs font-semibold uppercase tracking-wider text-stone-400">{{ t('monitor.endedAt') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="loading && !tasks.length">
              <td colspan="6" class="px-4 py-8 text-center text-sm text-stone-400"><span class="inline-block h-5 w-5 rounded-full border-2 border-stone-200 border-t-stone-500 animate-spin" /></td>
            </tr>
            <tr v-else-if="!tasks.length"><td colspan="6" class="px-4 py-8 text-center text-sm text-stone-400">{{ t('monitor.noTasks') }}</td></tr>
            <tr v-for="task in tasks" :key="task.id" class="transition-colors hover:bg-stone-50/50" :style="tasks.indexOf(task) % 2 !== 0 ? 'background: rgb(var(--stone-50-rgb) / 0.4)' : ''">
              <td class="whitespace-nowrap px-4 py-3 text-xs text-stone-400 font-mono">#{{ task.id }}</td>
              <td class="px-4 py-3 text-xs font-medium text-stone-700 max-w-[200px] truncate">{{ task.task_name }}</td>
              <td class="whitespace-nowrap px-4 py-3">
                <div class="flex flex-col gap-1">
                  <span class="badge" :class="[getStatusConfig(task.status).bg, getStatusConfig(task.status).text]"><span class="status-dot shrink-0" :class="getStatusConfig(task.status).dot" />{{ getStatusConfig(task.status).labelKey ? t(`monitor.${getStatusConfig(task.status).labelKey}`) : getStatusConfig(task.status).rawLabel }}</span>
                  <span v-if="task.error_msg" class="max-w-[180px] truncate text-2xs text-rose-500" :title="task.error_msg">{{ task.error_msg }}</span>
                </div>
              </td>
              <td class="whitespace-nowrap px-4 py-3 text-xs text-stone-500 tabular-nums">{{ task.item_count }}</td>
              <td class="whitespace-nowrap px-4 py-3 text-xs text-stone-400">{{ formatDate(task.started_at) }}</td>
              <td class="whitespace-nowrap px-4 py-3 text-xs text-stone-400"><span v-if="task.finished_at">{{ formatTime(task.finished_at) }}</span><span v-else class="text-stone-300">—</span></td>
            </tr>
          </tbody>
        </table>
      </div>

      <div class="flex items-center justify-between px-5 py-3 shrink-0" style="border-top: 1px solid rgb(var(--stone-400-rgb) / 0.15)">
        <p class="text-xs text-stone-400">{{ t('monitor.pageSummary', { page, totalPages, total }) }}</p>
        <div class="flex items-center gap-1">
          <button class="rounded-full px-2.5 py-1 text-xs font-medium text-stone-400 hover:bg-accent-soft disabled:opacity-30 disabled:cursor-not-allowed transition" :disabled="page <= 1" @click="emit('goPage', 1)">«</button>
          <button class="rounded-full px-3 py-1 text-xs font-medium text-stone-400 hover:bg-accent-soft disabled:opacity-30 disabled:cursor-not-allowed transition" :disabled="page <= 1" @click="emit('goPage', page - 1)">{{ t('monitor.previous') }}</button>
          <template v-for="targetPage in totalPages" :key="targetPage"><button v-if="Math.abs(targetPage - page) <= 2" class="rounded-full px-3 py-1 text-xs font-medium transition" :class="targetPage === page ? 'bg-accent text-accent-ink border border-ink shadow-sm' : 'text-stone-500 hover:bg-accent-soft hover:text-ink'" @click="emit('goPage', targetPage)">{{ targetPage }}</button></template>
          <button class="rounded-full px-3 py-1 text-xs font-medium text-stone-400 hover:bg-accent-soft disabled:opacity-30 disabled:cursor-not-allowed transition" :disabled="page >= totalPages" @click="emit('goPage', page + 1)">{{ t('monitor.next') }}</button>
          <button class="rounded-full px-2.5 py-1 text-xs font-medium text-stone-400 hover:bg-accent-soft disabled:opacity-30 disabled:cursor-not-allowed transition" :disabled="page >= totalPages" @click="emit('goPage', totalPages)">»</button>
        </div>
      </div>
    </div>
  </div>
</template>
