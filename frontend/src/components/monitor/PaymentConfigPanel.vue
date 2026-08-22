<script setup lang="ts">
import { useI18n } from 'vue-i18n'
const { t } = useI18n()
import PaymentSecretField from './PaymentSecretField.vue'
import {
  formatDate,
  type PaymentConfig,
  type PaymentConfigForm,
} from '@/features/monitor/monitorViewModel'

const props = defineProps<{
  config: PaymentConfig | null
  form: PaymentConfigForm
  loading: boolean
  saving: boolean
  resetting: boolean
}>()

const emit = defineEmits<{
  save: []
  reset: []
}>()

const updateForm = <K extends keyof PaymentConfigForm>(field: K, value: PaymentConfigForm[K]) => {
  // eslint-disable-next-line vue/no-mutating-props -- form 为父组件传入的草稿对象，此处为受控表单的有意回写
  props.form[field] = value
}

const sourceBadge = (source: PaymentConfig['source'] | undefined) => {
  if (source === 'database') return { class: 'monitor-status-success', label: t('monitor.paymentConfig.sourceDatabase') }
  if (source === 'environment') return { class: 'monitor-status-unknown', label: t('monitor.paymentConfig.sourceEnvironment') }
  return { class: 'monitor-status-unknown', label: t('monitor.paymentConfig.sourceUnconfigured') }
}

const channelBadge = (configured: boolean | undefined) =>
  configured
    ? { class: 'monitor-status-success', label: t('monitor.paymentConfig.channelConfigured') }
    : { class: 'monitor-status-unknown', label: t('monitor.paymentConfig.channelMissing') }
</script>

<template>
  <div class="stagger-enter glass-card shrink-0 p-5" style="animation-delay: 0.1s">
    <div class="mb-3 flex flex-wrap items-center gap-2">
      <svg class="h-4 w-4 monitor-caption" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="5" width="20" height="14" rx="2"/><line x1="2" y1="10" x2="22" y2="10"/></svg>
      <h3 class="monitor-section-title text-sm font-semibold">{{ t('monitor.paymentConfig.title') }}</h3>
      <span class="badge" :class="sourceBadge(config?.source).class">{{ sourceBadge(config?.source).label }}</span>
      <span class="badge" :class="channelBadge(config?.wechat_configured).class">{{ t('monitor.paymentConfig.wechat') }} · {{ channelBadge(config?.wechat_configured).label }}</span>
      <span class="badge" :class="channelBadge(config?.alipay_configured).class">{{ t('monitor.paymentConfig.alipay') }} · {{ channelBadge(config?.alipay_configured).label }}</span>
      <span class="badge" :class="channelBadge(config?.stripe_configured).class">Stripe · {{ channelBadge(config?.stripe_configured).label }}</span>
      <span v-if="config?.updated_at" class="ml-auto text-2xs monitor-caption">{{ t('monitor.updatedAt', { date: formatDate(config.updated_at) }) }}</span>
    </div>

    <!-- 总开关 + 通用区 -->
    <div class="grid grid-cols-1 gap-3 md:grid-cols-[minmax(150px,0.5fr)_minmax(150px,0.5fr)_minmax(260px,2fr)] md:items-end">
      <div class="flex items-end pb-2">
        <label class="inline-flex items-center gap-1.5 text-xs monitor-caption">
          <input :checked="form.enabled" type="checkbox" class="rounded border-stone-300 text-stone-700 focus:ring-stone-400" :disabled="loading || saving || resetting" @change="updateForm('enabled', ($event.target as HTMLInputElement).checked)" />
          {{ t('monitor.paymentConfig.enabled') }}
        </label>
      </div>
      <label class="block">
        <span class="mb-1 block text-xs monitor-caption">{{ t('monitor.paymentConfig.orderTtl') }}</span>
        <input :value="form.order_ttl_minutes" type="number" min="5" max="1440" class="input w-full py-2 text-xs" autocomplete="off" :disabled="loading || saving || resetting" @input="updateForm('order_ttl_minutes', Number(($event.target as HTMLInputElement).value) || 0)" />
      </label>
      <label class="block">
        <span class="mb-1 block text-xs monitor-caption">{{ t('monitor.paymentConfig.publicBaseUrl') }}</span>
        <input :value="form.public_base_url" type="text" class="input w-full py-2 text-xs" placeholder="https://pay.example.com" autocomplete="off" :disabled="loading || saving || resetting" @input="updateForm('public_base_url', ($event.target as HTMLInputElement).value)" />
      </label>
    </div>

    <!-- 微信支付 -->
    <div class="mt-4 border-t border-stone-200/60 pt-3 dark:border-stone-700/60">
      <div class="mb-2 flex items-center gap-2">
        <h4 class="text-xs font-semibold monitor-caption">{{ t('monitor.paymentConfig.wechat') }}</h4>
        <span class="text-2xs monitor-caption">{{ t('monitor.paymentConfig.secretWriteOnly') }}</span>
      </div>
      <div class="grid grid-cols-1 gap-3 md:grid-cols-3">
        <label class="block">
          <span class="mb-1 block text-xs monitor-caption">{{ t('monitor.paymentConfig.wechatAppid') }}</span>
          <input :value="form.wechat_appid" type="text" class="input w-full py-2 text-xs" autocomplete="off" :disabled="loading || saving || resetting" @input="updateForm('wechat_appid', ($event.target as HTMLInputElement).value)" />
        </label>
        <label class="block">
          <span class="mb-1 block text-xs monitor-caption">{{ t('monitor.paymentConfig.wechatMchid') }}</span>
          <input :value="form.wechat_mchid" type="text" class="input w-full py-2 text-xs" autocomplete="off" :disabled="loading || saving || resetting" @input="updateForm('wechat_mchid', ($event.target as HTMLInputElement).value)" />
        </label>
        <label class="block">
          <span class="mb-1 block text-xs monitor-caption">{{ t('monitor.paymentConfig.wechatMchSerialNo') }}</span>
          <input :value="form.wechat_mch_serial_no" type="text" class="input w-full py-2 text-xs" autocomplete="off" :disabled="loading || saving || resetting" @input="updateForm('wechat_mch_serial_no', ($event.target as HTMLInputElement).value)" />
        </label>
      </div>
      <div class="mt-3 grid grid-cols-1 gap-3 md:grid-cols-2">
        <PaymentSecretField field-key="wechat_api_v3_key" label-key="monitor.paymentConfig.wechatApiV3Key" :config="config" :form="form" :disabled="loading || saving || resetting" />
        <PaymentSecretField field-key="wechat_private_key_pem" label-key="monitor.paymentConfig.wechatPrivateKey" textarea :config="config" :form="form" :disabled="loading || saving || resetting" />
      </div>
    </div>

    <!-- 支付宝 -->
    <div class="mt-4 border-t border-stone-200/60 pt-3 dark:border-stone-700/60">
      <div class="mb-2 flex items-center gap-2">
        <h4 class="text-xs font-semibold monitor-caption">{{ t('monitor.paymentConfig.alipay') }}</h4>
        <span class="text-2xs monitor-caption">{{ t('monitor.paymentConfig.secretWriteOnly') }}</span>
      </div>
      <div class="grid grid-cols-1 gap-3 md:grid-cols-3">
        <label class="block">
          <span class="mb-1 block text-xs monitor-caption">{{ t('monitor.paymentConfig.alipayAppid') }}</span>
          <input :value="form.alipay_appid" type="text" class="input w-full py-2 text-xs" autocomplete="off" :disabled="loading || saving || resetting" @input="updateForm('alipay_appid', ($event.target as HTMLInputElement).value)" />
        </label>
      </div>
      <div class="mt-3 grid grid-cols-1 gap-3 md:grid-cols-2">
        <PaymentSecretField field-key="alipay_private_key_pem" label-key="monitor.paymentConfig.alipayPrivateKey" textarea :config="config" :form="form" :disabled="loading || saving || resetting" />
        <PaymentSecretField field-key="alipay_public_key_pem" label-key="monitor.paymentConfig.alipayPublicKey" textarea :config="config" :form="form" :disabled="loading || saving || resetting" />
      </div>
    </div>

    <!-- Stripe -->
    <div class="mt-4 border-t border-stone-200/60 pt-3 dark:border-stone-700/60">
      <div class="mb-2 flex items-center gap-2">
        <h4 class="text-xs font-semibold monitor-caption">{{ t('monitor.paymentConfig.stripe') }}</h4>
        <span class="text-2xs monitor-caption">{{ t('monitor.paymentConfig.secretWriteOnly') }}</span>
      </div>
      <div class="grid grid-cols-1 gap-3 md:grid-cols-2">
        <PaymentSecretField field-key="stripe_secret_key" label-key="monitor.paymentConfig.stripeSecretKey" :config="config" :form="form" :disabled="loading || saving || resetting" />
        <PaymentSecretField field-key="stripe_webhook_secret" label-key="monitor.paymentConfig.stripeWebhookSecret" :config="config" :form="form" :disabled="loading || saving || resetting" />
      </div>
    </div>

    <div class="mt-4 flex flex-wrap items-center gap-2">
      <button class="monitor-btn-primary" :disabled="saving || loading || resetting" @click="emit('save')">
        {{ t(saving ? 'monitor.saving' : 'monitor.saveConfig') }}
      </button>
      <!-- 删除 DB 覆盖行：整体回落环境变量；无覆盖行时等价于确认当前 env 口径 -->
      <button class="monitor-btn-secondary" :disabled="resetting || loading || saving" @click="emit('reset')">
        {{ t(resetting ? 'monitor.paymentConfig.resetting' : 'monitor.paymentConfig.resetToEnv') }}
      </button>
    </div>

    <div class="mt-3 text-xs monitor-caption monitor-check-row px-3 py-2">
      <span>{{ t('monitor.paymentConfig.hint') }}</span>
    </div>
  </div>
</template>
