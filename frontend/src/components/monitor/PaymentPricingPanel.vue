<script setup lang="ts">
import { useI18n } from 'vue-i18n'
const { t } = useI18n()
import type { PaymentPlanPricing, PaymentPlanPricingForm } from '@/features/monitor/monitorModel'
import { formatAmountCents } from '@/features/payments/paymentModel'

/**
 * 会员套餐定价面板：管理员运行时调整月付/年付价格（payment_plan_overrides），
 * 默认价权威在后端 plans.py。输入按元（最多两位小数），留空 = 恢复默认；
 * 调价只影响新订单，在途待支付订单按下单时快照金额收款。
 */
const props = defineProps<{
  plans: PaymentPlanPricing[]
  form: PaymentPlanPricingForm
  loading: boolean
  saving: boolean
}>()

const emit = defineEmits<{
  save: []
}>()

const updateForm = <K extends keyof PaymentPlanPricingForm>(field: K, value: PaymentPlanPricingForm[K]) => {
  // eslint-disable-next-line vue/no-mutating-props -- form 为父组件传入的草稿对象，此处为受控表单的有意回写
  props.form[field] = value
}

// 套餐目录被后端钉为四个（test_payment_plans.py），按码定点渲染四行；
// 美元行同样按「元」（美元单位、最多两位小数）录入，复用同一 yuanToCents 校验
const PLAN_ROWS = [
  { code: 'member_monthly', field: 'monthly_yuan', labelKey: 'monitor.paymentPricing.monthly' },
  { code: 'member_yearly', field: 'yearly_yuan', labelKey: 'monitor.paymentPricing.yearly' },
  { code: 'member_monthly_usd', field: 'monthly_usd', labelKey: 'monitor.paymentPricing.monthlyUsd' },
  { code: 'member_yearly_usd', field: 'yearly_usd', labelKey: 'monitor.paymentPricing.yearlyUsd' },
] as const

const planFor = (code: string) => props.plans.find((plan) => plan.code === code) ?? null
const amountText = (cents: number, currency: string) => formatAmountCents(cents, currency)
</script>

<template>
  <div class="stagger-enter glass-card shrink-0 p-5" style="animation-delay: 0.1s">
    <div class="mb-3 flex flex-wrap items-center gap-2">
      <svg class="h-4 w-4 monitor-caption" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2v20"/><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/></svg>
      <h3 class="monitor-section-title text-sm font-semibold">{{ t('monitor.paymentPricing.title') }}</h3>
      <span v-if="loading" class="text-2xs monitor-caption">{{ t('common.loading') }}</span>
    </div>

    <p class="mb-3 text-xs leading-5 monitor-caption monitor-check-row px-3 py-2">{{ t('monitor.paymentPricing.hint') }}</p>

    <div class="grid grid-cols-1 gap-3 md:grid-cols-2">
      <div v-for="row in PLAN_ROWS" :key="row.code" class="rounded-md border monitor-check-row px-3 py-2">
        <label class="block">
          <span class="mb-1 block text-xs monitor-caption">{{ t(row.labelKey) }}</span>
          <input
            :value="form[row.field]"
            type="text"
            inputmode="decimal"
            class="input w-full py-2 text-xs"
            :placeholder="planFor(row.code) ? String(planFor(row.code)!.default_amount_cents / 100) : ''"
            autocomplete="off"
            :disabled="saving || loading"
            @input="updateForm(row.field, ($event.target as HTMLInputElement).value)"
          />
        </label>
        <div v-if="planFor(row.code)" class="mt-2 flex flex-wrap items-center gap-2 text-2xs">
          <span class="badge">
            {{ t('monitor.paymentPricing.defaultPrice', { amount: amountText(planFor(row.code)!.default_amount_cents, planFor(row.code)!.currency) }) }}
          </span>
          <span class="badge">
            {{ t('monitor.paymentPricing.effectivePrice', { amount: amountText(planFor(row.code)!.amount_cents, planFor(row.code)!.currency) }) }}
          </span>
          <span v-if="planFor(row.code)!.override_amount_cents !== null" class="badge">
            {{ t('monitor.paymentPricing.overridden') }}
          </span>
          <span v-else class="badge">{{ t('monitor.paymentPricing.usingDefault') }}</span>
          <button
            v-if="planFor(row.code)!.override_amount_cents !== null || form[row.field] !== ''"
            type="button"
            class="text-2xs underline monitor-caption"
            :disabled="saving || loading"
            @click="updateForm(row.field, '')"
          >
            {{ t('monitor.paymentPricing.restoreDefault') }}
          </button>
        </div>
      </div>
    </div>

    <div class="mt-3 flex gap-2">
      <button class="monitor-btn-primary" :disabled="saving || loading" @click="emit('save')">
        {{ t(saving ? 'monitor.saving' : 'monitor.paymentPricing.save') }}
      </button>
    </div>
  </div>
</template>
