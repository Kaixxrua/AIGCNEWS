<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { Check, LoaderCircle, QrCode } from 'lucide-vue-next'
import { paymentApi } from '@/services/payments/paymentApi'
import { usePaymentCheckout } from '@/composables/usePaymentCheckout'
import {
  formatAmountCents,
  resolvePlan,
  type BillingPeriod,
  type PaymentChannel,
  type PaymentChannelAvailability,
  type PaymentPlan,
  PAYMENT_CHANNELS,
} from '@/features/payments/paymentModel'

defineOptions({ name: 'MembershipCheckoutView' })

/**
 * 收银台：金额/套餐只渲染 GET /api/payments/plans 响应（后端 plans.py 是唯一
 * 权威）；渠道 available=false 置灰（凭证未配置）。qr_code 指令骨架期渲染
 * 占位框 + 原文文本（不引二维码库，渠道接入后替换为真实二维码）。
 */
const { t } = useI18n()
const route = useRoute()
const router = useRouter()

const plansLoading = ref(true)
const plansFailed = ref(false)
const plan = ref<PaymentPlan | null>(null)
const channels = ref<PaymentChannelAvailability[]>([])
const selectedChannel = ref<PaymentChannel | null>(null)

const { phase, order, instruction, beginCheckout, restartCheckout, disposeCheckout } =
  usePaymentCheckout({ api: paymentApi })

const period = computed<BillingPeriod>(() =>
  route.query.plan === 'yearly' ? 'yearly' : 'monthly',
)

const CHANNEL_LABEL_KEYS: Record<PaymentChannel, string> = {
  wechat_native: 'membership.checkout.channelWechat',
  alipay_page: 'membership.checkout.channelAlipay',
  stripe: 'membership.checkout.channelStripe',
}

const channelAvailable = (channel: PaymentChannel) =>
  channels.value.find((item) => item.channel === channel)?.available ?? false

const amountLabel = computed(() =>
  plan.value ? formatAmountCents(plan.value.amount_cents, plan.value.currency) : '',
)
const periodSuffix = computed(() =>
  period.value === 'yearly'
    ? t('membership.checkout.perYear')
    : t('membership.checkout.perMonth'),
)

const submitting = computed(() => phase.value === 'creating')
const awaitingPayment = computed(() => phase.value === 'awaiting_payment')

onMounted(async () => {
  try {
    const response = await paymentApi.listPlans()
    plan.value = resolvePlan(response.plans, period.value)
    channels.value = response.channels
    if (!plan.value) {
      // 套餐缺失 = 收银台不可用，回会员页（联系兜底在那边）
      router.replace({ name: 'membership' })
      return
    }
    selectedChannel.value =
      PAYMENT_CHANNELS.find((channel) => channelAvailable(channel)) ?? null
  } catch (error) {
    console.error('Failed to load payment plans', error)
    plansFailed.value = true
  } finally {
    plansLoading.value = false
  }
})

onBeforeUnmount(disposeCheckout)

const selectChannel = (channel: PaymentChannel) => {
  if (!channelAvailable(channel)) return
  selectedChannel.value = channel
}

const submit = () => {
  if (!plan.value || !selectedChannel.value || submitting.value || awaitingPayment.value) return
  void beginCheckout(plan.value.code, selectedChannel.value)
}
</script>

<template>
  <div class="checkout-page">
    <div class="checkout-card glass-card">
      <header class="stagger-enter checkout-hero">
        <h1 class="checkout-title">{{ t('membership.checkout.title') }}</h1>
        <p class="checkout-subtitle">{{ t('membership.checkout.subtitle') }}</p>
      </header>

      <p v-if="plansLoading" class="checkout-note">{{ t('common.loading') }}</p>

      <template v-else-if="plansFailed">
        <p class="checkout-note">{{ t('membership.checkout.loadFailed') }}</p>
        <RouterLink to="/membership" class="checkout-back">
          {{ t('membership.checkout.backToMembership') }}
        </RouterLink>
      </template>

      <template v-else-if="plan">
        <!-- 订单摘要：金额只来自 plans API -->
        <section class="checkout-summary">
          <span class="checkout-plan-name">
            {{ period === 'yearly' ? t('membership.checkout.planYearly') : t('membership.checkout.planMonthly') }}
          </span>
          <span class="checkout-amount">
            {{ amountLabel }}<span class="checkout-amount-period">{{ periodSuffix }}</span>
          </span>
        </section>

        <!-- 渠道选择：available=false 置灰「即将开放」 -->
        <section class="checkout-channels" role="radiogroup" :aria-label="t('membership.checkout.channelTitle')">
          <p class="checkout-section-label">{{ t('membership.checkout.channelTitle') }}</p>
          <button
            v-for="channel in PAYMENT_CHANNELS"
            :key="channel"
            type="button"
            class="checkout-channel"
            :class="{
              'checkout-channel--selected': selectedChannel === channel,
              'checkout-channel--disabled': !channelAvailable(channel),
            }"
            role="radio"
            :aria-checked="selectedChannel === channel"
            :disabled="!channelAvailable(channel)"
            @click="selectChannel(channel)"
          >
            <span>{{ t(CHANNEL_LABEL_KEYS[channel]) }}</span>
            <span v-if="!channelAvailable(channel)" class="checkout-channel-soon">
              {{ t('membership.checkout.channelSoon') }}
            </span>
          </button>
        </section>

        <!-- 支付指令：qr_code 骨架期占位框 + 原文；redirect_url 直跳 -->
        <section v-if="instruction && awaitingPayment" class="checkout-instruction">
          <template v-if="instruction.kind === 'qr_code'">
            <div class="checkout-qr" aria-hidden="true">
              <QrCode :size="44" :stroke-width="1.5" />
              <span class="checkout-qr-label">{{ t('membership.checkout.qrPlaceholder') }}</span>
            </div>
            <p class="checkout-instruction-hint">{{ t('membership.checkout.scanHint') }}</p>
            <code class="checkout-instruction-raw">{{ instruction.content }}</code>
          </template>
          <template v-else-if="instruction.kind === 'redirect_url'">
            <p class="checkout-instruction-hint">{{ t('membership.checkout.redirectHint') }}</p>
            <a :href="instruction.content" class="checkout-redirect">{{ t('membership.checkout.redirectAction') }}</a>
          </template>
          <p class="checkout-awaiting">
            <LoaderCircle :size="14" class="checkout-spin" aria-hidden="true" />
            {{ t('membership.checkout.awaiting') }}
          </p>
          <p v-if="order" class="checkout-order-no">{{ t('membership.checkout.orderNo') }}：{{ order.order_no }}</p>
        </section>

        <!-- 终态 -->
        <section v-else-if="phase === 'paid'" class="checkout-result checkout-result--paid">
          <Check :size="28" :stroke-width="2.5" aria-hidden="true" />
          <p class="checkout-result-title">{{ t('membership.checkout.paid') }}</p>
          <p class="checkout-note">{{ t('membership.checkout.paidHint') }}</p>
          <RouterLink to="/membership" class="checkout-back">{{ t('membership.checkout.backToMembership') }}</RouterLink>
        </section>
        <section v-else-if="phase === 'expired' || phase === 'closed' || phase === 'poll_timeout'" class="checkout-result">
          <p class="checkout-result-title">
            {{ phase === 'poll_timeout' ? t('membership.checkout.pollTimeout') : t('membership.checkout.expired') }}
          </p>
          <button type="button" class="checkout-submit" @click="restartCheckout">
            {{ t('membership.checkout.retry') }}
          </button>
        </section>

        <template v-else>
          <button
            type="button"
            class="checkout-submit"
            :disabled="!selectedChannel || submitting"
            @click="submit"
          >
            {{ submitting ? t('membership.checkout.submitting') : t('membership.checkout.submit') }}
          </button>
          <p v-if="phase === 'create_failed'" class="checkout-error">
            {{ t('membership.checkout.createFailed') }}
          </p>
        </template>
      </template>
    </div>
  </div>
</template>

<style scoped>
/* Hallmark · component: checkout-panel · genre: editorial · theme: project-locked
 * (paper/acid/ink 既有 token，零新增色值；复用 membership 页的 tier-cta 配方)
 * states: default · selected · disabled · awaiting(spin) · paid · expired */
.checkout-page {
  width: 100%;
  height: 100%;
  overflow-y: auto;
  display: flex;
  justify-content: center;
  padding: 32px 24px 48px;
  box-sizing: border-box;
}

.checkout-card {
  width: 100%;
  max-width: 520px;
  height: fit-content;
  padding: 28px 26px 26px;
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.checkout-hero {
  text-align: center;
}

.checkout-title {
  font-size: 24px;
  font-weight: 700;
  color: var(--ink);
  margin: 0 0 8px;
  font-family: 'Playfair Display', serif;
}

.checkout-subtitle {
  font-size: 13px;
  line-height: 1.7;
  color: var(--ink-muted);
  margin: 0;
}

.checkout-note {
  margin: 0;
  font-size: 13px;
  color: var(--ink-muted);
  text-align: center;
}

.checkout-summary {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  padding: 14px 16px;
  border: 1px solid var(--rule-strong);
  border-radius: var(--module-radius);
  background: var(--paper-raised);
}

.checkout-plan-name {
  font-size: 13px;
  font-weight: 800;
  color: var(--ink-secondary);
}

.checkout-amount {
  font-family: 'Playfair Display', serif;
  font-size: 30px;
  font-weight: 700;
  color: var(--ink);
}

.checkout-amount-period {
  margin-left: 4px;
  font-size: 13px;
  font-family: inherit;
  font-weight: 400;
  color: var(--ink-muted);
}

.checkout-section-label {
  margin: 0 0 8px;
  font-size: 12px;
  font-weight: 800;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--ink-muted);
}

.checkout-channels {
  display: flex;
  flex-direction: column;
}

.checkout-channel {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border: 1px solid var(--rule);
  border-radius: var(--control-radius);
  background: var(--paper-raised);
  color: var(--ink);
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: border-color 150ms ease, background-color 150ms ease;
}

.checkout-channel + .checkout-channel {
  margin-top: 8px;
}

.checkout-channel:hover:not(:disabled) {
  background: var(--acid-soft);
}

.checkout-channel--selected {
  border-color: var(--ink);
  border-width: 2px;
}

.checkout-channel--disabled {
  cursor: not-allowed;
  color: var(--ink-faint);
}

.checkout-channel-soon {
  font-size: 11px;
  font-weight: 700;
  color: var(--ink-faint);
}

.checkout-instruction {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  padding: 18px 16px;
  border: 1px dashed var(--rule-strong);
  border-radius: var(--module-radius);
}

.checkout-qr {
  width: 180px;
  height: 180px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  border: 1px solid var(--rule-strong);
  border-radius: var(--control-radius);
  background: var(--paper-raised);
  color: var(--ink-muted);
}

.checkout-qr-label {
  font-size: 12px;
  font-weight: 600;
}

.checkout-instruction-hint {
  margin: 0;
  font-size: 13px;
  color: var(--ink-secondary);
  text-align: center;
}

.checkout-instruction-raw {
  max-width: 100%;
  overflow-wrap: anywhere;
  font-size: 11px;
  color: var(--ink-faint);
}

.checkout-redirect {
  display: inline-flex;
  padding: 10px 18px;
  border-radius: var(--control-radius);
  background: var(--ink);
  color: var(--btn-primary-label);
  font-size: 14px;
  font-weight: 800;
  text-decoration: none;
}

.checkout-awaiting {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  margin: 0;
  font-size: 12px;
  color: var(--ink-muted);
}

.checkout-spin {
  animation: checkout-rotate 1.2s linear infinite;
}

@keyframes checkout-rotate {
  to { transform: rotate(360deg); }
}

@media (prefers-reduced-motion: reduce) {
  .checkout-spin {
    animation: none;
  }
}

.checkout-order-no {
  margin: 0;
  font-size: 11px;
  color: var(--ink-faint);
}

.checkout-result {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  padding: 12px 0 4px;
  text-align: center;
}

.checkout-result--paid {
  color: var(--projects-success);
}

.checkout-result-title {
  margin: 0;
  font-size: 15px;
  font-weight: 800;
  color: var(--ink);
}

.checkout-submit {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 11px 20px;
  border-radius: var(--control-radius);
  background: var(--ink);
  color: var(--btn-primary-label);
  border: 2px solid var(--ink);
  font-size: 14px;
  font-weight: 800;
  cursor: pointer;
  transition: background-color 150ms ease, color 150ms ease, transform 150ms ease;
}

.checkout-submit:hover:not(:disabled) {
  background: var(--acid);
  color: var(--acid-ink);
}

.checkout-submit:active:not(:disabled) {
  transform: translateY(1px);
}

.checkout-submit:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}

.checkout-error {
  margin: 0;
  font-size: 12px;
  text-align: center;
  color: var(--projects-danger, #c0392b);
}

.checkout-back {
  display: inline-flex;
  justify-content: center;
  padding: 10px 18px;
  border-radius: var(--control-radius);
  border: 1px solid var(--rule-strong);
  color: var(--ink);
  font-size: 13px;
  font-weight: 700;
  text-decoration: none;
}

.checkout-back:hover {
  background: var(--acid-soft);
}

@media (max-width: 639px) {
  .checkout-page {
    padding: 20px 14px 32px;
  }
}
</style>
