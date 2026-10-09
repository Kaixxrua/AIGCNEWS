<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { OAuthConfig, OAuthConfigForm } from '@/features/monitor/monitorViewModel'

// 密钥字段 key 与后端 oauth_settings 密文列一一对应；只写入、不回显。
type OAuthSecretFieldKey =
  | 'github_client_secret'
  | 'google_client_secret'
  | 'wechat_app_secret'
  | 'qq_client_secret'
  | 'linuxdo_client_secret'

const { t } = useI18n()

const props = withDefaults(defineProps<{
  fieldKey: OAuthSecretFieldKey
  labelKey: string
  config: OAuthConfig | null
  form: OAuthConfigForm
  disabled?: boolean
}>(), { disabled: false })

// 已配置时只显示脱敏 badge；留空 = 保留当前值，勾选 clear = 保存时擦除
const configured = computed(
  () => props.config?.[`${props.fieldKey}_configured` as keyof OAuthConfig] as boolean | undefined,
)
const masked = computed(
  () => props.config?.[`${props.fieldKey}_masked` as keyof OAuthConfig] as string | null | undefined,
)
const clearKey = computed(() => `clear_${props.fieldKey}` as keyof OAuthConfigForm)

const updateForm = <K extends keyof OAuthConfigForm>(field: K, value: OAuthConfigForm[K]) => {
  // eslint-disable-next-line vue/no-mutating-props -- form 为父组件传入的草稿对象，此处为受控表单的有意回写
  props.form[field] = value
}
</script>

<template>
  <div>
    <div class="mb-1 flex items-center gap-2">
      <span class="text-xs monitor-caption">{{ t(labelKey) }}</span>
      <span v-if="configured" class="badge monitor-status-success">{{ masked }}</span>
      <label v-if="configured" class="inline-flex items-center gap-1 text-2xs monitor-caption">
        <input
          :checked="form[clearKey] as boolean"
          type="checkbox"
          class="rounded border-stone-300 text-stone-700 focus:ring-stone-400"
          :disabled="disabled"
          @change="updateForm(clearKey, ($event.target as HTMLInputElement).checked)"
        />
        {{ t('monitor.oauthConfig.clearSecret') }}
      </label>
    </div>
    <input
      :value="form[fieldKey]"
      type="password"
      class="input w-full py-2 text-xs"
      :placeholder="t('monitor.oauthConfig.retainSecret')"
      autocomplete="new-password"
      :disabled="disabled"
      @input="updateForm(fieldKey, ($event.target as HTMLInputElement).value)"
    />
  </div>
</template>
