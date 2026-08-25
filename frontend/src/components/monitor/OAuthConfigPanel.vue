<script setup lang="ts">
import { useI18n } from 'vue-i18n'
const { t } = useI18n()
import OAuthSecretField from './OAuthSecretField.vue'
import {
  formatDate,
  type OAuthConfig,
  type OAuthConfigForm,
  type OAuthProviderKey,
} from '@/features/monitor/monitorViewModel'

const props = defineProps<{
  config: OAuthConfig | null
  form: OAuthConfigForm
  loading: boolean
  saving: boolean
  resetting: boolean
}>()

const emit = defineEmits<{
  save: []
  reset: []
}>()

const PROVIDERS: { key: OAuthProviderKey; labelKey: string }[] = [
  { key: 'github', labelKey: 'monitor.oauthConfig.providerGithub' },
  { key: 'google', labelKey: 'monitor.oauthConfig.providerGoogle' },
  { key: 'wechat', labelKey: 'monitor.oauthConfig.providerWechat' },
]

const updateForm = <K extends keyof OAuthConfigForm>(field: K, value: OAuthConfigForm[K]) => {
  // eslint-disable-next-line vue/no-mutating-props -- form 为父组件传入的草稿对象，此处为受控表单的有意回写
  props.form[field] = value
}

const toggleProvider = (provider: OAuthProviderKey, enabled: boolean) => {
  const current = props.form.enabled_providers.filter(item => item !== provider)
  updateForm('enabled_providers', enabled ? [...current, provider] : current)
}

const sourceBadge = (source: OAuthConfig['source'] | undefined) => {
  if (source === 'database') return { class: 'monitor-status-success', label: t('monitor.oauthConfig.sourceDatabase') }
  if (source === 'environment') return { class: 'monitor-status-unknown', label: t('monitor.oauthConfig.sourceEnvironment') }
  return { class: 'monitor-status-unknown', label: t('monitor.oauthConfig.sourceUnconfigured') }
}

const providerBadge = (provider: OAuthProviderKey) => {
  const enabled = props.form.enabled_providers.includes(provider)
  return enabled
    ? { class: 'monitor-status-success', label: t('monitor.oauthConfig.providerEnabled') }
    : { class: 'monitor-status-unknown', label: t('monitor.oauthConfig.providerDisabled') }
}
</script>

<template>
  <div class="stagger-enter glass-card shrink-0 p-5" style="animation-delay: 0.1s">
    <div class="mb-3 flex flex-wrap items-center gap-2">
      <svg class="h-4 w-4 monitor-caption" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4"/><polyline points="10 17 15 12 10 7"/><line x1="15" y1="12" x2="3" y2="12"/></svg>
      <h3 class="monitor-section-title text-sm font-semibold">{{ t('monitor.oauthConfig.title') }}</h3>
      <span class="badge" :class="sourceBadge(config?.source).class">{{ sourceBadge(config?.source).label }}</span>
      <span v-for="provider in PROVIDERS" :key="provider.key" class="badge" :class="providerBadge(provider.key).class">
        {{ t(provider.labelKey) }} · {{ providerBadge(provider.key).label }}
      </span>
      <span v-if="config?.updated_at" class="ml-auto text-2xs monitor-caption">{{ t('monitor.updatedAt', { date: formatDate(config.updated_at) }) }}</span>
    </div>

    <!-- 通用区：公网基址 + TTL -->
    <div class="grid grid-cols-1 gap-3 md:grid-cols-[minmax(280px,2fr)_minmax(140px,0.6fr)_minmax(140px,0.6fr)] md:items-end">
      <label class="block">
        <span class="mb-1 block text-xs monitor-caption">{{ t('monitor.oauthConfig.publicBaseUrl') }}</span>
        <input :value="form.public_base_url" type="text" class="input w-full py-2 text-xs" placeholder="https://www.aigcnews.cn" autocomplete="off" :disabled="loading || saving || resetting" @input="updateForm('public_base_url', ($event.target as HTMLInputElement).value)" />
      </label>
      <label class="block">
        <span class="mb-1 block text-xs monitor-caption">{{ t('monitor.oauthConfig.stateTtl') }}</span>
        <input :value="form.state_ttl_seconds" type="number" min="60" max="900" class="input w-full py-2 text-xs" autocomplete="off" :disabled="loading || saving || resetting" @input="updateForm('state_ttl_seconds', Number(($event.target as HTMLInputElement).value) || 0)" />
      </label>
      <label class="block">
        <span class="mb-1 block text-xs monitor-caption">{{ t('monitor.oauthConfig.handoffTtl') }}</span>
        <input :value="form.handoff_ttl_seconds" type="number" min="30" max="600" class="input w-full py-2 text-xs" autocomplete="off" :disabled="loading || saving || resetting" @input="updateForm('handoff_ttl_seconds', Number(($event.target as HTMLInputElement).value) || 0)" />
      </label>
    </div>

    <!-- Provider 区块 -->
    <div v-for="provider in PROVIDERS" :key="provider.key" class="mt-4 border-t border-stone-200/60 pt-3 dark:border-stone-700/60">
      <div class="mb-2 flex items-center gap-2">
        <h4 class="text-xs font-semibold monitor-caption">{{ t(provider.labelKey) }}</h4>
        <label class="inline-flex items-center gap-1.5 text-xs monitor-caption">
          <input
            :checked="form.enabled_providers.includes(provider.key)"
            type="checkbox"
            class="rounded border-stone-300 text-stone-700 focus:ring-stone-400"
            :disabled="loading || saving || resetting"
            @change="toggleProvider(provider.key, ($event.target as HTMLInputElement).checked)"
          />
          {{ t('monitor.oauthConfig.enableProvider') }}
        </label>
        <span class="text-2xs monitor-caption">{{ t('monitor.oauthConfig.secretWriteOnly') }}</span>
      </div>
      <div class="grid grid-cols-1 gap-3 md:grid-cols-2">
        <label class="block">
          <span class="mb-1 block text-xs monitor-caption">
            {{ provider.key === 'wechat' ? t('monitor.oauthConfig.appId') : t('monitor.oauthConfig.clientId') }}
          </span>
          <input
            :value="provider.key === 'github' ? form.github_client_id : provider.key === 'google' ? form.google_client_id : form.wechat_app_id"
            type="text"
            class="input w-full py-2 text-xs"
            autocomplete="off"
            :disabled="loading || saving || resetting"
            @input="updateForm(provider.key === 'github' ? 'github_client_id' : provider.key === 'google' ? 'google_client_id' : 'wechat_app_id', ($event.target as HTMLInputElement).value)"
          />
        </label>
        <OAuthSecretField
          :field-key="provider.key === 'github' ? 'github_client_secret' : provider.key === 'google' ? 'google_client_secret' : 'wechat_app_secret'"
          :label-key="provider.key === 'wechat' ? 'monitor.oauthConfig.appSecret' : 'monitor.oauthConfig.clientSecret'"
          :config="config"
          :form="form"
          :disabled="loading || saving || resetting"
        />
      </div>
    </div>

    <div class="mt-4 flex flex-wrap items-center gap-2">
      <button class="monitor-btn-primary" :disabled="saving || loading || resetting" @click="emit('save')">
        {{ t(saving ? 'monitor.saving' : 'monitor.saveConfig') }}
      </button>
      <!-- 删除 DB 覆盖行：整体回落环境变量；无覆盖行时等价于确认当前 env 口径 -->
      <button class="monitor-btn-secondary" :disabled="resetting || loading || saving" @click="emit('reset')">
        {{ t(resetting ? 'monitor.oauthConfig.resetting' : 'monitor.oauthConfig.resetToEnv') }}
      </button>
    </div>

    <div class="mt-3 text-xs monitor-caption monitor-check-row px-3 py-2">
      <span>{{ t('monitor.oauthConfig.hint') }}</span>
    </div>
  </div>
</template>
