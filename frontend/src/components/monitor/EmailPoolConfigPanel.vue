<script setup lang="ts">
import { useI18n } from 'vue-i18n'
const { t } = useI18n()
import {
  formatDate,
} from '@/features/monitor/monitorViewModel'
import {
  createEmailPoolEntryForm,
  type EmailPoolConfig,
  type EmailPoolEntryForm,
  type EmailPoolForm,
} from '@/features/monitor/monitorModel'

const props = defineProps<{
  config: EmailPoolConfig | null
  form: EmailPoolForm
  loading: boolean
  saving: boolean
  testing: boolean
}>()

const emit = defineEmits<{
  save: []
  test: []
}>()

const MAX_ENTRIES = 20

const updateEntry = <K extends keyof EmailPoolEntryForm>(index: number, field: K, value: EmailPoolEntryForm[K]) => {
  const entry = props.form.entries[index]
  if (!entry) return
  // eslint-disable-next-line vue/no-mutating-props -- form 为父组件传入的草稿对象，此处为受控表单的有意回写
  entry[field] = value
}

const addEntry = () => {
  // eslint-disable-next-line vue/no-mutating-props -- 同上：受控草稿的动态列表增行
  props.form.entries.push(createEmailPoolEntryForm())
}

const removeEntry = (index: number) => {
  // eslint-disable-next-line vue/no-mutating-props -- 同上：受控草稿的动态列表删行
  props.form.entries.splice(index, 1)
}

const sourceBadge = (source: EmailPoolConfig['source'] | undefined) => {
  if (source === 'database') return { class: 'monitor-status-success', label: t('monitor.emailPoolConfig.sourceDatabase') }
  if (source === 'environment') return { class: 'monitor-status-unknown', label: t('monitor.emailPoolConfig.sourceEnvironment') }
  return { class: 'monitor-status-unknown', label: t('monitor.emailPoolConfig.sourceUnconfigured') }
}

/** 已存密码徽标按 name 匹配（与后端 retain-by-name 同键）：改名后徽标消失，
 *  正好可视化"改名丢密码"语义；表单行顺序与已保存顺序无关 */
const passwordBadge = (entry: EmailPoolEntryForm) => {
  const saved = props.config?.entries?.find((item) => item.name === entry.name.trim())
  return saved?.password_configured && saved.password_masked ? saved.password_masked : ''
}
</script>

<template>
  <div class="stagger-enter glass-card shrink-0 p-5" style="animation-delay: 0.12s">
    <div class="mb-3 flex flex-wrap items-center gap-2">
      <svg class="h-4 w-4 monitor-caption" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 6h16M4 12h16M4 18h16"/><circle cx="8" cy="6" r="1.6" fill="currentColor" stroke="none"/><circle cx="14" cy="12" r="1.6" fill="currentColor" stroke="none"/><circle cx="10" cy="18" r="1.6" fill="currentColor" stroke="none"/></svg>
      <h3 class="monitor-section-title text-sm font-semibold">{{ t('monitor.emailPoolConfig.title') }}</h3>
      <span class="badge" :class="sourceBadge(config?.source).class">{{ sourceBadge(config?.source).label }}</span>
      <span v-if="config?.entries?.length" class="badge monitor-status-unknown">{{ t('monitor.emailPoolConfig.entryCount', { count: config.entries.length }) }}</span>
      <span v-if="config?.updated_at" class="ml-auto text-2xs monitor-caption">{{ t('monitor.updatedAt', { date: formatDate(config.updated_at) }) }}</span>
    </div>

    <div v-if="!form.entries.length" class="monitor-check-row mb-3 px-3 py-2 text-xs monitor-caption">
      {{ t('monitor.emailPoolConfig.empty') }}
    </div>

    <div v-for="(entry, index) in form.entries" :key="index" class="monitor-check-row mb-3 px-3 py-2">
      <div class="mb-2 flex flex-wrap items-end gap-2">
        <label class="block">
          <span class="mb-1 block text-xs monitor-caption">{{ t('monitor.emailPoolConfig.name') }}</span>
          <input :value="entry.name" type="text" class="input w-36 py-2 text-xs" placeholder="brevo" autocomplete="off" :disabled="loading || saving" @input="updateEntry(index, 'name', ($event.target as HTMLInputElement).value.trim())" />
        </label>
        <span v-if="passwordBadge(entry)" class="badge monitor-status-success">{{ t('monitor.emailPoolConfig.passwordConfigured') }}: {{ passwordBadge(entry) }}</span>
        <button class="monitor-btn-secondary ml-auto" :disabled="loading || saving" :title="t('monitor.emailPoolConfig.removeEntry')" @click="removeEntry(index)">×</button>
      </div>
      <div class="grid grid-cols-2 gap-2 md:grid-cols-3 lg:grid-cols-[minmax(170px,1.2fr)_minmax(76px,0.4fr)_minmax(130px,0.8fr)_minmax(150px,1fr)] lg:items-end">
        <label class="block">
          <span class="mb-1 block text-xs monitor-caption">{{ t('monitor.emailPoolConfig.host') }}</span>
          <input :value="entry.host" type="text" class="input w-full py-2 text-xs" placeholder="smtp-relay.example.com" autocomplete="off" :disabled="loading || saving" @input="updateEntry(index, 'host', ($event.target as HTMLInputElement).value.trim())" />
        </label>
        <label class="block">
          <span class="mb-1 block text-xs monitor-caption">{{ t('monitor.emailPoolConfig.port') }}</span>
          <input :value="entry.port" type="number" min="1" max="65535" class="input w-full py-2 text-xs" autocomplete="off" :disabled="loading || saving" @input="updateEntry(index, 'port', Number(($event.target as HTMLInputElement).value) || 0)" />
        </label>
        <label class="block">
          <span class="mb-1 block text-xs monitor-caption">{{ t('monitor.emailPoolConfig.username') }}</span>
          <input :value="entry.username" type="text" class="input w-full py-2 text-xs" autocomplete="off" :disabled="loading || saving" @input="updateEntry(index, 'username', ($event.target as HTMLInputElement).value.trim())" />
        </label>
        <label class="block">
          <span class="mb-1 block text-xs monitor-caption">{{ t('monitor.emailPoolConfig.password') }}</span>
          <input :value="entry.password" type="password" class="input w-full py-2 text-xs" :placeholder="t('monitor.emailPoolConfig.retainPassword')" autocomplete="new-password" :disabled="loading || saving" @input="updateEntry(index, 'password', ($event.target as HTMLInputElement).value)" />
        </label>
        <label class="block">
          <span class="mb-1 block text-xs monitor-caption">{{ t('monitor.emailPoolConfig.fromEmail') }}</span>
          <input :value="entry.from_email" type="email" class="input w-full py-2 text-xs" :placeholder="t('monitor.emailPoolConfig.fromEmailInherit')" autocomplete="off" :disabled="loading || saving" @input="updateEntry(index, 'from_email', ($event.target as HTMLInputElement).value.trim())" />
        </label>
        <label class="block">
          <span class="mb-1 block text-xs monitor-caption">{{ t('monitor.emailPoolConfig.fromName') }}</span>
          <input :value="entry.from_name" type="text" class="input w-full py-2 text-xs" :placeholder="t('monitor.emailPoolConfig.fromNameInherit')" autocomplete="off" :disabled="loading || saving" @input="updateEntry(index, 'from_name', ($event.target as HTMLInputElement).value)" />
        </label>
        <label class="block">
          <span class="mb-1 block text-xs monitor-caption">{{ t('monitor.emailPoolConfig.dailyLimit') }}</span>
          <input :value="entry.daily_limit" type="number" min="0" class="input w-full py-2 text-xs" autocomplete="off" :disabled="loading || saving" @input="updateEntry(index, 'daily_limit', Math.max(0, Number(($event.target as HTMLInputElement).value) || 0))" />
        </label>
        <label class="block">
          <span class="mb-1 block text-xs monitor-caption">{{ t('monitor.emailPoolConfig.monthlyLimit') }}</span>
          <input :value="entry.monthly_limit" type="number" min="0" class="input w-full py-2 text-xs" autocomplete="off" :disabled="loading || saving" @input="updateEntry(index, 'monthly_limit', Math.max(0, Number(($event.target as HTMLInputElement).value) || 0))" />
        </label>
        <label class="block">
          <span class="mb-1 block text-xs monitor-caption">{{ t('monitor.emailPoolConfig.priority') }}</span>
          <input :value="entry.priority" type="number" class="input w-full py-2 text-xs" autocomplete="off" :disabled="loading || saving" @input="updateEntry(index, 'priority', Number(($event.target as HTMLInputElement).value) || 0)" />
        </label>
        <div class="flex items-end gap-3 pb-2">
          <label class="inline-flex items-center gap-1.5 text-xs monitor-caption">
            <input :checked="entry.use_tls" type="checkbox" class="rounded border-stone-300 text-stone-700 focus:ring-stone-400" :disabled="loading || saving" @change="updateEntry(index, 'use_tls', ($event.target as HTMLInputElement).checked)" />
            {{ t('monitor.emailPoolConfig.useTls') }}
          </label>
          <label class="inline-flex items-center gap-1.5 text-xs monitor-caption">
            <input :checked="entry.clear_password" type="checkbox" class="rounded border-stone-300 text-stone-700 focus:ring-stone-400" :disabled="loading || saving" @change="updateEntry(index, 'clear_password', ($event.target as HTMLInputElement).checked)" />
            {{ t('monitor.emailPoolConfig.clearPassword') }}
          </label>
        </div>
      </div>
    </div>

    <div class="flex flex-wrap items-center gap-2">
      <button class="monitor-btn-secondary" :disabled="loading || saving || form.entries.length >= MAX_ENTRIES" @click="addEntry">
        + {{ t('monitor.emailPoolConfig.addEntry') }}
      </button>
      <!-- 测试针对最新生效（已保存/env）池配置，经真实 failover 链路投递 -->
      <button
        class="monitor-btn-secondary"
        :disabled="testing || saving || loading || !config || config.source === 'unconfigured'"
        :title="t('monitor.emailPoolConfig.testTitle')"
        @click="emit('test')"
      >
        {{ t(testing ? 'monitor.emailPoolConfig.testing' : 'monitor.emailPoolConfig.testSend') }}
      </button>
      <button class="monitor-btn-primary ml-auto" :disabled="saving || loading || testing" @click="emit('save')">
        {{ t(saving ? 'monitor.saving' : 'monitor.saveConfig') }}
      </button>
    </div>

    <div class="mt-3 text-xs monitor-caption monitor-check-row px-3 py-2">
      {{ t('monitor.emailPoolConfig.hint') }}
    </div>
  </div>
</template>
