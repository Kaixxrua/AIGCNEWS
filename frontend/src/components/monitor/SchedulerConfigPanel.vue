<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import SkeletonBlock from '@/components/SkeletonBlock.vue'
import type { SchedulerJobConfig, SchedulerJobConfigForm } from '@/features/monitor/monitorModel'

const { t } = useI18n()

const props = defineProps<{
  configs: SchedulerJobConfig[]
  form: SchedulerJobConfigForm
  loading: boolean
  saving: boolean
  editingJobId: string | null
}>()

const emit = defineEmits<{
  edit: [job: SchedulerJobConfig]
  cancel: []
  save: []
}>()

const isEditing = computed(() => props.editingJobId !== null)
const editingJob = computed(() => props.configs.find((item) => item.job_id === props.editingJobId))

const updateForm = <K extends keyof SchedulerJobConfigForm>(field: K, value: SchedulerJobConfigForm[K]) => {
  // eslint-disable-next-line vue/no-mutating-props -- form 为父组件传入的草稿对象，此处为受控表单的有意回写
  props.form[field] = value
}

const formatWindow = (job: SchedulerJobConfig) => `${job.start_time} – ${job.end_time}`
const formatInterval = (minutes: number) => {
  if (minutes < 60) return `${minutes}m`
  if (minutes % 1440 === 0) return `${minutes / 1440}d`
  if (minutes % 60 === 0) return `${minutes / 60}h`
  return `${Math.floor(minutes / 60)}h ${minutes % 60}m`
}
</script>

<template>
  <div class="stagger-enter glass-card flex flex-col p-5" style="animation-delay: 0.15s;">
    <div class="mb-4 flex items-center justify-between">
      <h3 class="monitor-section-title text-sm font-semibold">{{ t('monitor.schedulerConfig.title') }}</h3>
      <span class="monitor-badge">{{ t('monitor.schedulerConfig.count', { count: configs.length }) }}</span>
    </div>

    <div v-if="loading" class="flex flex-col gap-3" role="status" :aria-label="t('common.loading')">
      <SkeletonBlock v-for="i in 4" :key="i" :width="i % 2 ? '92%' : '70%'" height="12px" />
    </div>

    <div v-else class="space-y-3">
      <div v-if="isEditing" class="monitor-surface p-4">
        <p class="text-xs font-semibold mb-3">{{ editingJob?.name || form.job_id }}</p>
        <div class="grid grid-cols-1 sm:grid-cols-3 gap-3">
          <div class="flex flex-col gap-1">
            <label class="text-2xs monitor-caption">{{ t('monitor.schedulerConfig.startTime') }}</label>
            <input :value="form.start_time" type="time" class="input px-2 py-1.5 text-sm rounded border" @input="updateForm('start_time', ($event.target as HTMLInputElement).value)" />
          </div>
          <div class="flex flex-col gap-1">
            <label class="text-2xs monitor-caption">{{ t('monitor.schedulerConfig.endTime') }}</label>
            <input :value="form.end_time" type="time" class="input px-2 py-1.5 text-sm rounded border" @input="updateForm('end_time', ($event.target as HTMLInputElement).value)" />
          </div>
          <div class="flex flex-col gap-1">
            <label class="text-2xs monitor-caption">{{ t('monitor.schedulerConfig.intervalMinutes') }}</label>
            <input :value="form.interval_minutes" type="number" min="1" class="input px-2 py-1.5 text-sm rounded border" @input="updateForm('interval_minutes', Number(($event.target as HTMLInputElement).value))" />
          </div>
        </div>
        <div class="mt-3 flex items-center gap-2">
          <label class="flex items-center gap-2 text-sm cursor-pointer">
            <input :checked="form.enabled" type="checkbox" class="h-4 w-4" @change="updateForm('enabled', ($event.target as HTMLInputElement).checked)" />
            {{ t('monitor.schedulerConfig.enabled') }}
          </label>
        </div>
        <div class="mt-4 flex flex-wrap gap-2">
          <button class="monitor-btn-primary" :disabled="saving" @click="emit('save')">
            {{ saving ? t('common.processing') : t('common.save') }}
          </button>
          <button class="monitor-btn-secondary" :disabled="saving" @click="emit('cancel')">
            {{ t('common.cancel') }}
          </button>
        </div>
        <p class="mt-3 text-2xs monitor-caption">{{ t('monitor.schedulerConfig.restartHint') }}</p>
      </div>

      <div class="overflow-x-auto">
        <table class="monitor-table">
          <thead>
            <tr>
              <th>{{ t('monitor.schedulerConfig.jobName') }}</th>
              <th>{{ t('monitor.schedulerConfig.window') }}</th>
              <th>{{ t('monitor.schedulerConfig.interval') }}</th>
              <th>{{ t('monitor.schedulerConfig.status') }}</th>
              <th class="text-right">{{ t('common.edit') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="job in configs" :key="job.job_id">
              <td class="max-w-[240px] truncate text-xs font-medium" :title="job.name">{{ job.name }}</td>
              <td class="text-xs tabular-nums">{{ formatWindow(job) }}</td>
              <td class="text-xs tabular-nums">{{ formatInterval(job.interval_minutes) }}</td>
              <td>
                <span class="badge" :class="job.enabled ? 'monitor-status-success' : 'monitor-status-unknown'">
                  {{ job.enabled ? t('monitor.schedulerConfig.active') : t('monitor.schedulerConfig.paused') }}
                </span>
              </td>
              <td class="text-right">
                <button class="monitor-btn-ghost" :disabled="isEditing" @click="emit('edit', job)">
                  {{ t('common.edit') }}
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>
