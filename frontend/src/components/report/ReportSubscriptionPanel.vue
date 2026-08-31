<script setup lang="ts">
import { useI18n } from 'vue-i18n'
const { t } = useI18n()
import { Bot, Mail, Rss } from 'lucide-vue-next'
import {
  REPORT_TYPES,
  type PlanDeliveryCapability,
  type ReportKey,
} from '@/features/report/reportViewModel'

defineProps<{
  showLoginPrompt: boolean
  showSubscribePanel: boolean
  isSubscribing: boolean
  isLoadingPlan: boolean
  isRssBusy: boolean
  rssNotice: string
  isMember: boolean
  userEmail: string
  step: 1 | 2
  selectedSources: ReportKey[]
  selectedDeliveryKeys: string[]
  deliveryCapabilities: PlanDeliveryCapability[]
  canSelectMultipleSources: boolean
  hasExistingPlan: boolean
}>()

const emit = defineEmits<{
  closeLoginPrompt: []
  loginAndRedirect: []
  closeSubscribePanel: []
  toggleSubscribeSource: [source: ReportKey]
  goNext: []
  goBack: []
  toggleDelivery: [key: string]
  copyRss: [member: boolean]
  rotateRss: []
  confirmPlan: []
}>()

const channelTypeLabel = (channelType?: string): string => {
  if (!channelType) return t('subscriptions.channels.platform.generic')
  const key = `subscriptions.channels.platform.${channelType}` as const
  const mapped = t(key)
  if (mapped !== key) return mapped
  if (channelType === 'email') return t('auth.email')
  if (channelType === 'wechat') return '微信'
  if (channelType === 'feishu') return '飞书'
  return channelType
}

const capabilityIcon = (cap: PlanDeliveryCapability) => {
  if (cap.kind === 'rss') return Rss
  if (cap.kind === 'account_email') return Mail
  return Bot
}
</script>

<template>
  <!-- 游客订阅登录提示 -->
  <div v-if="showLoginPrompt" class="rounded-2xl border p-3 shadow-sm" style="border-color: var(--notice-warn-edge); background: var(--notice-warn-bg-strong)">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <div class="flex items-center gap-2 text-sm" style="color: var(--notice-warn-ink)">
        <Rss class="h-4 w-4 shrink-0" />
        <span>{{ t('report.loginRequired') }}</span>
      </div>
      <div class="flex items-center gap-2">
        <button class="rounded-full px-3 py-1.5 text-xs font-medium hover:bg-[var(--notice-warn-edge)]" style="color: var(--notice-warn-ink-soft)" @click="emit('closeLoginPrompt')">{{ t('report.later') }}</button>
        <button class="rounded-full bg-amber-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-amber-700" @click="emit('loginAndRedirect')">{{ t('report.goLogin') }}</button>
      </div>
    </div>
  </div>

  <!-- 日报订阅向导 -->
  <div v-if="showSubscribePanel" class="rounded-2xl border bg-card/90 p-3 shadow-sm" style="border-color: var(--panel-edge-info)">
    <!-- 步骤指示器 -->
    <div class="mb-3 flex items-center gap-2">
      <span class="flex h-5 w-5 items-center justify-center rounded-full text-[10px] font-bold" :class="step === 1 ? 'bg-ink text-paper' : 'bg-stone-200 text-stone-600'">1</span>
      <span class="text-xs" :class="step === 1 ? 'font-semibold text-stone-800' : 'text-stone-400'">{{ t('report.wizard.step1Title') }}</span>
      <span class="h-px flex-1 bg-stone-200" />
      <span class="flex h-5 w-5 items-center justify-center rounded-full text-[10px] font-bold" :class="step === 2 ? 'bg-ink text-paper' : 'bg-stone-200 text-stone-600'">2</span>
      <span class="text-xs" :class="step === 2 ? 'font-semibold text-stone-800' : 'text-stone-400'">{{ t('report.wizard.step2Title') }}</span>
    </div>

    <!-- 步骤 1：选择日报模块 -->
    <template v-if="step === 1">
      <div class="flex items-start justify-between gap-3">
        <div>
          <p class="text-sm font-semibold text-stone-700">{{ t('report.wizard.step1Title') }}</p>
          <p class="text-2xs text-stone-400 mt-0.5">{{ t('report.wizard.step1Description') }}</p>
          <p v-if="!isMember && !canSelectMultipleSources" class="text-2xs mt-1" style="color: var(--notice-warn-ink)">
            {{ t('report.freeTierHint') }}
            <RouterLink to="/membership" class="font-semibold underline underline-offset-2">{{ t('report.upgradeCta') }}</RouterLink>
          </p>
        </div>
        <button class="text-2xs text-stone-400 hover:text-stone-600" :disabled="isSubscribing" @click="emit('closeSubscribePanel')">{{ t('common.cancel') }}</button>
      </div>

      <div class="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
        <button
          v-for="type in REPORT_TYPES"
          :key="type.key"
          type="button"
          class="flex items-center gap-2 rounded-xl border px-3 py-2 text-left transition-all duration-200"
          :class="selectedSources.includes(type.key)
            ? 'border-indigo-200 bg-indigo-50 text-indigo-800'
            : 'border-stone-100 bg-card/70 text-stone-600 hover:bg-accent-soft'"
          :disabled="isSubscribing || isLoadingPlan"
          @click="emit('toggleSubscribeSource', type.key)"
        >
          <span class="flex h-4 w-4 items-center justify-center rounded border text-[10px]"
            :class="selectedSources.includes(type.key) ? 'border-indigo-500 bg-indigo-500 text-white' : 'border-stone-300 text-transparent'">✓</span>
          <component :is="type.icon" class="h-4 w-4 shrink-0" />
          <span class="min-w-0 flex-1">
            <span class="block text-xs font-semibold">{{ t(`report.type.${type.labelKey}`) }}</span>
            <span class="block text-2xs opacity-70">{{ t(`report.type.${type.descKey}`) }}</span>
          </span>
        </button>
      </div>

      <div class="mt-3 flex items-center justify-end gap-2">
        <button
          class="rounded-full px-3 py-1.5 text-xs font-medium text-stone-500 hover:bg-accent-soft"
          :disabled="isSubscribing"
          @click="emit('closeSubscribePanel')"
        >{{ t('common.cancel') }}</button>
        <button
          class="btn-primary gap-1.5 text-xs py-1.5 px-3"
          :disabled="isSubscribing || (!selectedSources.length && !hasExistingPlan) || isLoadingPlan"
          @click="emit('goNext')"
        >
          <span v-if="isLoadingPlan" class="h-3 w-3 rounded-full border-2 animate-spin" style="border-color: color-mix(in srgb, currentColor 40%, transparent); border-top-color: currentColor" />
          {{ t('report.wizard.next') }}
        </button>
      </div>
    </template>

    <!-- 步骤 2：选择订阅方式 -->
    <template v-else>
      <div class="flex items-start justify-between gap-3">
        <div>
          <p class="text-sm font-semibold text-stone-700">{{ t('report.wizard.step2Title') }}</p>
          <p class="text-2xs text-stone-400 mt-0.5">{{ t('report.wizard.step2Description') }}</p>
        </div>
        <button class="text-2xs text-stone-400 hover:text-stone-600" :disabled="isSubscribing" @click="emit('closeSubscribePanel')">{{ t('common.cancel') }}</button>
      </div>

      <div class="mt-3 grid gap-2 sm:grid-cols-2">
        <div
          v-for="cap in deliveryCapabilities"
          :key="cap.key"
          class="delivery-option flex items-stretch gap-2 rounded-xl border text-left transition-all duration-200"
          :class="[
            cap.selectable && selectedDeliveryKeys.includes(cap.key)
              ? 'delivery-option--selected border-indigo-200 bg-indigo-50 text-indigo-800'
              : 'border-stone-200 bg-card/70 text-stone-600',
            !cap.selectable && 'cursor-not-allowed opacity-60',
          ]"
        >
          <button
            type="button"
            class="delivery-option__toggle flex min-w-0 flex-1 items-start gap-2 rounded-lg px-3 py-2 text-left hover:bg-accent-soft disabled:cursor-not-allowed"
            :disabled="isSubscribing || !cap.selectable"
            :aria-pressed="selectedDeliveryKeys.includes(cap.key)"
            @click="emit('toggleDelivery', cap.key)"
          >
            <span class="mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded border text-[10px]"
              :class="selectedDeliveryKeys.includes(cap.key) && cap.selectable ? 'border-indigo-500 bg-indigo-500 text-white' : 'border-stone-300 text-transparent'">✓</span>
            <component :is="capabilityIcon(cap)" class="mt-0.5 h-4 w-4 shrink-0" />
            <span class="min-w-0 flex-1">
              <span class="block text-xs font-semibold">
                <template v-if="cap.kind === 'rss'">{{ t('report.wizard.delivery.rssTitle') }}</template>
                <template v-else-if="cap.kind === 'account_email'">{{ t('report.wizard.delivery.accountEmailTitle') }}</template>
                <template v-else-if="cap.status === 'coming_soon'">{{ channelTypeLabel(cap.channel_type) }} · {{ t('report.wizard.delivery.comingSoonSuffix') }}</template>
                <template v-else>{{ channelTypeLabel(cap.channel_type) }}{{ cap.target ? ` · ${cap.target}` : '' }}</template>
              </span>
              <span class="block text-2xs opacity-70">
                <template v-if="cap.kind === 'rss'">{{ t('report.wizard.delivery.rssDescription') }}</template>
                <template v-else-if="cap.kind === 'account_email'">{{ t('report.wizard.delivery.accountEmailDescription', { email: userEmail }) }}</template>
                <template v-else-if="cap.status === 'coming_soon'">{{ t('report.wizard.delivery.comingSoonDescription') }}</template>
                <template v-else-if="!cap.verified">{{ t('report.wizard.delivery.unverified') }}</template>
                <template v-else-if="cap.status !== 'active'">{{ t('report.wizard.delivery.disabled') }}</template>
                <template v-else>{{ t('report.wizard.delivery.pushChannelDescription') }}</template>
              </span>
            </span>
          </button>
          <div v-if="cap.kind === 'rss'" class="flex shrink-0 flex-col items-stretch justify-center gap-1 border-l border-stone-200 p-2">
            <button
              type="button"
              class="btn-secondary justify-center px-2 py-1 text-2xs"
              :disabled="isRssBusy"
              @click="emit('copyRss', false)"
            >{{ t('report.wizard.delivery.copyPublic') }}</button>
            <button
              v-if="isMember"
              type="button"
              class="btn-secondary justify-center px-2 py-1 text-2xs"
              :disabled="isRssBusy"
              @click="emit('copyRss', true)"
            >{{ t('report.wizard.delivery.copyMember') }}</button>
            <button
              v-if="isMember"
              type="button"
              class="btn-ghost justify-center px-2 py-1 text-2xs"
              :disabled="isRssBusy"
              @click="emit('rotateRss')"
            >{{ t('report.wizard.delivery.resetToken') }}</button>
          </div>
        </div>
      </div>

      <p class="mt-2 text-2xs text-stone-400">{{ t('report.wizard.rssNote') }}</p>
      <p v-if="rssNotice" class="mt-1 text-2xs text-emerald-700">
        {{ rssNotice === 'rss-rotated' ? t('report.wizard.rssResetSuccess') : t('report.wizard.rssCopied') }}
      </p>

      <div class="mt-3 flex items-center justify-end gap-2">
        <div class="flex items-center gap-2">
          <button
            class="btn-secondary px-3 py-1.5 text-xs"
            :disabled="isSubscribing"
            @click="emit('goBack')"
          >{{ t('report.wizard.back') }}</button>
          <button
            class="btn-primary gap-1.5 text-xs py-1.5 px-3"
            :disabled="isSubscribing || (!selectedDeliveryKeys.length && selectedSources.length > 0 && !isMember)"
            @click="emit('confirmPlan')"
          >
            <span v-if="isSubscribing" class="h-3 w-3 rounded-full border-2 animate-spin" style="border-color: color-mix(in srgb, currentColor 40%, transparent); border-top-color: currentColor" />
            {{ selectedSources.length || selectedDeliveryKeys.length ? t('report.wizard.submit', { count: selectedSources.length }) : t('report.wizard.unsubscribe') }}
          </button>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.delivery-option {
  border-color: var(--rule-strong);
  background: var(--paper-raised);
  color: var(--ink-secondary);
}

.delivery-option--selected {
  border-color: var(--ink);
  background: var(--acid-bright);
  color: var(--chat-on-acid);
}

.delivery-option__toggle:focus-visible {
  outline: 2px solid var(--ink);
  outline-offset: 2px;
}
</style>
