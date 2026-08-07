<script setup lang="ts">
import { useI18n } from 'vue-i18n'
const { t } = useI18n()
import {
  formatDate,
  type ProviderConfig,
  type ProviderForm,
} from '@/features/monitor/monitorViewModel'

const props = defineProps<{
  config: ProviderConfig | null
  form: ProviderForm
  loading: boolean
  saving: boolean
}>()

const emit = defineEmits<{
  save: []
}>()

const updateForm = <K extends keyof ProviderForm>(field: K, value: ProviderForm[K]) => {
  // eslint-disable-next-line vue/no-mutating-props -- form 为父组件传入的草稿对象，此处为受控表单的有意回写
  props.form[field] = value
}
</script>

<template>
  <div class="stagger-enter glass-card shrink-0 p-5" style="animation-delay: 0.08s">
    <div class="mb-3 flex flex-wrap items-center gap-2">
      <svg class="h-4 w-4 monitor-caption" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2v20"/><path d="M2 12h20"/><circle cx="12" cy="12" r="4"/></svg>
      <h3 class="monitor-section-title text-sm font-semibold">{{ t('monitor.providerTitle') }}</h3>
      <span v-if="config?.api_key_configured" class="badge monitor-status-success">Key: {{ config.api_key_masked }}</span>
      <span v-else class="badge monitor-status-unknown">{{ t('monitor.keyMissing') }}</span>
      <span v-if="config?.updated_at" class="ml-auto text-2xs monitor-caption">{{ t('monitor.updatedAt', { date: formatDate(config.updated_at) }) }}</span>
    </div>

    <div class="grid grid-cols-1 gap-3 lg:grid-cols-[130px_minmax(200px,1fr)_minmax(160px,0.8fr)_minmax(130px,0.6fr)_minmax(190px,1fr)_auto] lg:items-end">
      <label class="block">
        <span class="mb-1 block text-xs monitor-caption">Provider</span>
        <select :value="form.provider" class="input w-full py-2 text-xs" :disabled="loading || saving" @change="updateForm('provider', ($event.target as HTMLSelectElement).value as ProviderForm['provider'])">
          <option value="openai">{{ t('monitor.openAiCompatible') }}</option>
          <option value="anthropic">Anthropic</option>
        </select>
      </label>
      <label class="block">
        <span class="mb-1 block text-xs monitor-caption">Base URL</span>
        <input :value="form.base_url" type="url" class="input w-full py-2 text-xs" placeholder="https://api.example.com/v1" autocomplete="off" @input="updateForm('base_url', ($event.target as HTMLInputElement).value.trim())" />
      </label>
      <label class="block">
        <span class="mb-1 block text-xs monitor-caption">{{ t('monitor.model') }}</span>
        <input :value="form.model_name" type="text" class="input w-full py-2 text-xs" :placeholder="t('monitor.modelPlaceholder')" autocomplete="off" @input="updateForm('model_name', ($event.target as HTMLInputElement).value.trim())" />
      </label>
      <label class="block">
        <span class="mb-1 block text-xs monitor-caption">{{ t('monitor.reasoningEffort') }}</span>
        <select :value="form.reasoning_effort" class="input w-full py-2 text-xs" :disabled="loading || saving" @change="updateForm('reasoning_effort', ($event.target as HTMLSelectElement).value as ProviderForm['reasoning_effort'])">
          <option value="">{{ t('monitor.reasoningEffortDefault') }}</option>
          <option value="minimal">minimal</option>
          <option value="low">low</option>
          <option value="medium">medium</option>
          <option value="high">high</option>
        </select>
      </label>
      <label class="block">
        <span class="mb-1 block text-xs monitor-caption">API Key</span>
        <input :value="form.api_key" type="password" class="input w-full py-2 text-xs" :placeholder="t('monitor.retainKey')" autocomplete="new-password" @input="updateForm('api_key', ($event.target as HTMLInputElement).value)" />
      </label>
      <button class="monitor-btn-primary" :disabled="saving || loading" @click="emit('save')">
        {{ t(saving ? 'monitor.saving' : 'monitor.saveConfig') }}
      </button>
    </div>

    <div class="mt-3 flex flex-wrap items-center gap-3 text-xs monitor-caption monitor-check-row px-3 py-2">
      <label class="inline-flex items-center gap-1.5">
        <input :checked="form.clear_api_key" type="checkbox" class="rounded border-stone-300 text-stone-700 focus:ring-stone-400" @change="updateForm('clear_api_key', ($event.target as HTMLInputElement).checked)" />
        {{ t('monitor.clearKey') }}
      </label>
      <span>{{ t('monitor.providerHint') }}</span>
      <span>{{ t('monitor.reasoningEffortHint') }}</span>
    </div>
  </div>
</template>
