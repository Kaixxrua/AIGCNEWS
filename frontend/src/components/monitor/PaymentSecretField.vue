<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { PaymentConfig, PaymentConfigForm } from '@/features/monitor/monitorViewModel'

// 密钥字段 key 与后端 payment_settings 密文列一一对应；只写入、不回显。
type PaymentSecretFieldKey =
  | 'wechat_api_v3_key'
  | 'wechat_private_key_pem'
  | 'wechat_public_key_pem'
  | 'alipay_private_key_pem'
  | 'alipay_public_key_pem'
  | 'stripe_secret_key'
  | 'stripe_webhook_secret'

const { t } = useI18n()

const props = withDefaults(defineProps<{
  fieldKey: PaymentSecretFieldKey
  labelKey: string
  config: PaymentConfig | null
  form: PaymentConfigForm
  disabled?: boolean
  textarea?: boolean
}>(), { disabled: false, textarea: false })

// 已配置时只显示脱敏 badge；留空 = 保留当前值，勾选 clear = 保存时擦除
const configured = computed(
  () => props.config?.[`${props.fieldKey}_configured` as keyof PaymentConfig] as boolean | undefined,
)
const masked = computed(
  () => props.config?.[`${props.fieldKey}_masked` as keyof PaymentConfig] as string | null | undefined,
)
const clearKey = computed(() => `clear_${props.fieldKey}` as keyof PaymentConfigForm)

const updateForm = <K extends keyof PaymentConfigForm>(field: K, value: PaymentConfigForm[K]) => {
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
        {{ t('monitor.paymentConfig.clearSecret') }}
      </label>
    </div>
    <textarea
      v-if="textarea"
      :value="form[fieldKey]"
      rows="3"
      class="input w-full py-2 text-xs font-mono"
      :placeholder="t('monitor.paymentConfig.retainSecret')"
      autocomplete="off"
      spellcheck="false"
      :disabled="disabled"
      @input="updateForm(fieldKey, ($event.target as HTMLTextAreaElement).value)"
    />
    <input
      v-else
      :value="form[fieldKey]"
      type="password"
      class="input w-full py-2 text-xs"
      :placeholder="t('monitor.paymentConfig.retainSecret')"
      autocomplete="new-password"
      :disabled="disabled"
      @input="updateForm(fieldKey, ($event.target as HTMLInputElement).value)"
    />
  </div>
</template>
