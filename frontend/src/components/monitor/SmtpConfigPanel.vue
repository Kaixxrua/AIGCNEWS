<script setup lang="ts">
import { useI18n } from 'vue-i18n'
const { t } = useI18n()
import {
  formatDate,
  type SmtpConfig,
  type SmtpForm,
} from '@/features/monitor/monitorViewModel'

const props = defineProps<{
  config: SmtpConfig | null
  form: SmtpForm
  loading: boolean
  saving: boolean
  testing: boolean
}>()

const emit = defineEmits<{
  save: []
  test: []
}>()

const updateForm = <K extends keyof SmtpForm>(field: K, value: SmtpForm[K]) => {
  // eslint-disable-next-line vue/no-mutating-props -- form 为父组件传入的草稿对象，此处为受控表单的有意回写
  props.form[field] = value
}

const sourceBadge = (source: SmtpConfig['source'] | undefined) => {
  if (source === 'database') return { class: 'monitor-status-success', label: t('monitor.smtpConfig.sourceDatabase') }
  if (source === 'environment') return { class: 'monitor-status-unknown', label: t('monitor.smtpConfig.sourceEnvironment') }
  return { class: 'monitor-status-unknown', label: t('monitor.smtpConfig.sourceUnconfigured') }
}
</script>

<template>
  <div class="stagger-enter glass-card shrink-0 p-5" style="animation-delay: 0.1s">
    <div class="mb-3 flex flex-wrap items-center gap-2">
      <svg class="h-4 w-4 monitor-caption" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="4" width="20" height="16" rx="2"/><path d="m2 7 10 6L22 7"/></svg>
      <h3 class="monitor-section-title text-sm font-semibold">{{ t('monitor.smtpConfig.title') }}</h3>
      <span class="badge" :class="sourceBadge(config?.source).class">{{ sourceBadge(config?.source).label }}</span>
      <span v-if="config?.password_configured" class="badge monitor-status-success">{{ t('monitor.smtpConfig.password') }}: {{ config.password_masked }}</span>
      <span v-else class="badge monitor-status-unknown">{{ t('monitor.smtpConfig.passwordMissing') }}</span>
      <span v-if="config?.updated_at" class="ml-auto text-2xs monitor-caption">{{ t('monitor.updatedAt', { date: formatDate(config.updated_at) }) }}</span>
    </div>

    <div class="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-[minmax(200px,1.2fr)_minmax(90px,0.4fr)_minmax(150px,0.8fr)_minmax(190px,1fr)] lg:items-end">
      <label class="block">
        <span class="mb-1 block text-xs monitor-caption">{{ t('monitor.smtpConfig.host') }}</span>
        <input :value="form.host" type="text" class="input w-full py-2 text-xs" placeholder="smtp.example.com" autocomplete="off" :disabled="loading || saving" @input="updateForm('host', ($event.target as HTMLInputElement).value.trim())" />
      </label>
      <label class="block">
        <span class="mb-1 block text-xs monitor-caption">{{ t('monitor.smtpConfig.port') }}</span>
        <input :value="form.port" type="number" min="1" max="65535" class="input w-full py-2 text-xs" autocomplete="off" :disabled="loading || saving" @input="updateForm('port', Number(($event.target as HTMLInputElement).value) || 0)" />
      </label>
      <label class="block">
        <span class="mb-1 block text-xs monitor-caption">{{ t('monitor.smtpConfig.username') }}</span>
        <input :value="form.username" type="text" class="input w-full py-2 text-xs" autocomplete="off" :disabled="loading || saving" @input="updateForm('username', ($event.target as HTMLInputElement).value.trim())" />
      </label>
      <label class="block">
        <span class="mb-1 block text-xs monitor-caption">{{ t('monitor.smtpConfig.password') }}</span>
        <input :value="form.password" type="password" class="input w-full py-2 text-xs" :placeholder="t('monitor.smtpConfig.retainPassword')" autocomplete="new-password" :disabled="loading || saving" @input="updateForm('password', ($event.target as HTMLInputElement).value)" />
      </label>
      <label class="block">
        <span class="mb-1 block text-xs monitor-caption">{{ t('monitor.smtpConfig.fromEmail') }}</span>
        <input :value="form.from_email" type="email" class="input w-full py-2 text-xs" placeholder="no-reply@example.com" autocomplete="off" :disabled="loading || saving" @input="updateForm('from_email', ($event.target as HTMLInputElement).value.trim())" />
      </label>
      <label class="block">
        <span class="mb-1 block text-xs monitor-caption">{{ t('monitor.smtpConfig.fromName') }}</span>
        <input :value="form.from_name" type="text" class="input w-full py-2 text-xs" placeholder="AIGC Radar" autocomplete="off" :disabled="loading || saving" @input="updateForm('from_name', ($event.target as HTMLInputElement).value)" />
      </label>
      <div class="flex items-end gap-4 pb-2">
        <label class="inline-flex items-center gap-1.5 text-xs monitor-caption">
          <input :checked="form.use_tls" type="checkbox" class="rounded border-stone-300 text-stone-700 focus:ring-stone-400" :disabled="loading || saving" @change="updateForm('use_tls', ($event.target as HTMLInputElement).checked)" />
          {{ t('monitor.smtpConfig.useTls') }}
        </label>
      </div>
      <div class="flex gap-2">
        <!-- 测试针对最新生效（已保存/env）配置；表单未保存的修改不参与 -->
        <button
          class="monitor-btn-secondary"
          :disabled="testing || saving || loading || !config || config.source === 'unconfigured'"
          :title="t('monitor.smtpConfig.testTitle')"
          @click="emit('test')"
        >
          {{ t(testing ? 'monitor.smtpConfig.testing' : 'monitor.smtpConfig.testSend') }}
        </button>
        <button class="monitor-btn-primary" :disabled="saving || loading || testing" @click="emit('save')">
          {{ t(saving ? 'monitor.saving' : 'monitor.saveConfig') }}
        </button>
      </div>
    </div>

    <div class="mt-3 flex flex-wrap items-center gap-3 text-xs monitor-caption monitor-check-row px-3 py-2">
      <label class="inline-flex items-center gap-1.5">
        <input :checked="form.clear_password" type="checkbox" class="rounded border-stone-300 text-stone-700 focus:ring-stone-400" @change="updateForm('clear_password', ($event.target as HTMLInputElement).checked)" />
        {{ t('monitor.smtpConfig.clearPassword') }}
      </label>
      <span>{{ t('monitor.smtpConfig.hint') }}</span>
    </div>
  </div>
</template>
