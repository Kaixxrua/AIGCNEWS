<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { MailPlus, RefreshCw, Send, Trash2, Webhook } from 'lucide-vue-next'
import SpinnerLoader from '@/components/SpinnerLoader.vue'
import { useSubscriptionsController } from '@/composables/useSubscriptionsController'
import { useAuthStore } from '@/stores/authStore'
import {
  SUBSCRIPTION_SOURCES,
  detectWebhookPlatform,
} from '@/features/subscriptions/subscriptionsModel'
import type { PushChannel, UserSubscription } from '@/features/subscriptions/subscriptionsModel'

defineOptions({ name: 'SubscriptionsView' })

const { t, te } = useI18n()
const ctl = useSubscriptionsController()
const authStore = useAuthStore()

const errorText = computed(() => {
  const key = `subscriptions.errors.${ctl.error.value}`
  return ctl.error.value && te(key) ? t(key) : ctl.error.value
})
const noticeText = computed(() => {
  const key = `subscriptions.notice.${ctl.notice.value}`
  return ctl.notice.value && te(key) ? t(key) : ''
})

const webhookPlatformLabel = computed(() =>
  t(`subscriptions.channels.platform.${detectWebhookPlatform(ctl.webhookInput.value)}`),
)

// 免费档 1 个日报模块上限（会员/admin 不限）：已达上限且当前选择的不是
// 已活跃模块时置灰新增按钮；同模块换渠道属存量变更，后端放行，不置灰。
// 跨体系（邮件简报）占用由后端 403 兜底 → subscriptions.errors.quota-exceeded。
const activeDailySources = computed(() =>
  ctl.subscriptions.value
    .filter((subscription) => subscription.status === 'active')
    .map((subscription) => subscription.source),
)
const subscriptionQuotaReached = computed(
  () =>
    !authStore.isMember &&
    !authStore.isAdmin &&
    activeDailySources.value.length >= 1 &&
    !activeDailySources.value.includes(ctl.newSource.value),
)

const channelTypeLabel = (channel: PushChannel): string =>
  channel.channel_type === 'webhook'
    ? t(`subscriptions.channels.platform.${detectWebhookPlatform(channel.target)}`)
    : t('subscriptions.channels.emailLabel')

const confirmRemoveChannel = (channel: PushChannel): void => {
  if (window.confirm(t('subscriptions.channels.deleteConfirm'))) {
    void ctl.removeChannel(channel)
  }
}
const confirmRemoveSubscription = (subscription: UserSubscription): void => {
  if (window.confirm(t('subscriptions.subs.deleteConfirm'))) {
    void ctl.removeSubscription(subscription)
  }
}

onMounted(() => {
  void ctl.loadAll()
})
</script>

<template>
  <div class="flex h-full min-h-0 flex-col overflow-hidden">
    <div class="flex min-h-0 flex-1 flex-col gap-5 overflow-y-auto p-6 pb-24">
      <!-- 页头 -->
      <div class="stagger-enter flex flex-wrap items-center justify-between gap-3 shrink-0">
        <div>
          <h1 class="text-2xl font-bold tracking-tight">{{ t('subscriptions.title') }}</h1>
          <p class="mt-0.5 text-sm text-stone-400">{{ t('subscriptions.description') }}</p>
        </div>
        <button
          type="button"
          class="inline-flex items-center gap-1.5 rounded-[4px] border border-ink px-2.5 py-1.5 text-xs font-bold transition-colors hover:bg-accent"
          :disabled="ctl.loading.value"
          @click="ctl.loadAll"
        >
          <RefreshCw class="h-3.5 w-3.5" :class="{ 'animate-spin': ctl.loading.value }" />
          {{ t('subscriptions.refresh') }}
        </button>
      </div>

      <p v-if="errorText" class="shrink-0 rounded-[4px] border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-700">
        {{ errorText }}
      </p>
      <p v-if="noticeText" class="shrink-0 rounded-[4px] border border-emerald-300 bg-emerald-50 px-3 py-2 text-sm text-emerald-700">
        {{ noticeText }}
      </p>

      <div class="grid min-h-0 flex-1 items-start gap-5 lg:grid-cols-2">
        <!-- 渠道管理 -->
        <section class="stagger-enter glass-card flex flex-col gap-4 p-4" style="animation-delay: 0.05s">
          <div class="flex items-center justify-between">
            <h2 class="text-base font-bold text-stone-800">{{ t('subscriptions.channels.title') }}</h2>
            <span class="text-2xs text-stone-400">
              {{ t('subscriptions.channels.count', { count: ctl.channels.value.length }) }}
            </span>
          </div>

          <!-- 邮箱渠道：验证码两步 -->
          <form class="flex flex-col gap-2" @submit.prevent="ctl.submitEmailChannel">
            <label class="flex items-center gap-1.5 text-xs font-bold text-stone-500">
              <MailPlus class="h-3.5 w-3.5" />
              {{ t('subscriptions.channels.emailTitle') }}
            </label>
            <div class="flex gap-2">
              <input
                v-model="ctl.emailInput.value"
                type="email"
                :placeholder="t('subscriptions.channels.emailPlaceholder')"
                class="min-w-0 flex-1 rounded-[4px] border border-stone-200 bg-white px-2.5 py-1.5 text-sm outline-none focus:border-ink"
              />
              <button
                type="submit"
                class="shrink-0 rounded-[4px] border border-ink bg-ink px-3 py-1.5 text-xs font-bold text-accent transition-colors hover:bg-accent hover:text-accent-ink disabled:opacity-40"
                :disabled="!ctl.canSubmitEmail.value"
              >
                {{ t('subscriptions.channels.emailSubmit') }}
              </button>
            </div>
            <div v-if="ctl.otpChannelId.value !== null" class="flex flex-col gap-2 rounded-[4px] border border-accent bg-accent/10 p-2.5">
              <span class="text-2xs text-stone-500">{{ t('subscriptions.channels.otpHint') }}</span>
              <div class="flex gap-2">
                <input
                  v-model="ctl.otpCode.value"
                  inputmode="numeric"
                  maxlength="6"
                  :placeholder="t('subscriptions.channels.otpPlaceholder')"
                  class="min-w-0 flex-1 rounded-[4px] border border-stone-200 bg-white px-2.5 py-1.5 text-sm tracking-[0.3em] outline-none focus:border-ink"
                />
                <button
                  type="button"
                  class="shrink-0 rounded-[4px] border border-ink bg-ink px-3 py-1.5 text-xs font-bold text-accent transition-colors hover:bg-accent hover:text-accent-ink disabled:opacity-40"
                  :disabled="!ctl.canSubmitOtp.value"
                  @click="ctl.submitOtp"
                >
                  {{ t('subscriptions.channels.otpSubmit') }}
                </button>
              </div>
            </div>
          </form>

          <!-- Webhook 渠道：探测即验证 -->
          <form class="flex flex-col gap-2" @submit.prevent="ctl.submitWebhookChannel">
            <label class="flex items-center gap-1.5 text-xs font-bold text-stone-500">
              <Webhook class="h-3.5 w-3.5" />
              {{ t('subscriptions.channels.webhookTitle') }}
            </label>
            <div class="flex gap-2">
              <input
                v-model="ctl.webhookInput.value"
                type="url"
                :placeholder="t('subscriptions.channels.webhookPlaceholder')"
                class="min-w-0 flex-1 rounded-[4px] border border-stone-200 bg-white px-2.5 py-1.5 text-sm outline-none focus:border-ink"
              />
              <button
                type="submit"
                class="shrink-0 rounded-[4px] border border-ink bg-ink px-3 py-1.5 text-xs font-bold text-accent transition-colors hover:bg-accent hover:text-accent-ink disabled:opacity-40"
                :disabled="!ctl.canSubmitWebhook.value"
              >
                {{ t('subscriptions.channels.webhookSubmit') }}
              </button>
            </div>
            <span class="text-2xs leading-relaxed text-stone-400">
              {{ webhookPlatformLabel }} · {{ t('subscriptions.channels.webhookHint') }}
            </span>
          </form>

          <!-- 渠道列表 -->
          <SpinnerLoader v-if="ctl.loading.value && !ctl.channels.value.length" class="min-h-[96px]" :size="22" />
          <ul v-else-if="ctl.channels.value.length" class="flex flex-col divide-y divide-stone-100">
            <li v-for="channel in ctl.channels.value" :key="channel.id" class="flex items-center gap-2 py-2.5">
              <span class="flex h-7 w-7 shrink-0 items-center justify-center rounded-[4px] border border-ink bg-accent text-accent-ink">
                <Webhook v-if="channel.channel_type === 'webhook'" class="h-4 w-4" />
                <MailPlus v-else class="h-4 w-4" />
              </span>
              <div class="min-w-0 flex-1">
                <div class="flex items-center gap-1.5">
                  <span class="text-2xs font-bold text-stone-500">{{ channelTypeLabel(channel) }}</span>
                  <span
                    class="rounded-[3px] px-1 text-[10px] font-bold"
                    :class="channel.verified ? 'bg-emerald-100 text-emerald-700' : 'bg-amber-100 text-amber-700'"
                  >
                    {{ channel.verified ? t('subscriptions.channels.verified') : t('subscriptions.channels.unverified') }}
                  </span>
                  <span
                    v-if="channel.status !== 'active'"
                    class="rounded-[3px] bg-stone-100 px-1 text-[10px] font-bold text-stone-500"
                  >
                    {{ t('subscriptions.channels.disabled') }}
                  </span>
                </div>
                <div class="truncate text-sm text-stone-700" :title="channel.target">{{ channel.target }}</div>
              </div>
              <div class="flex shrink-0 items-center gap-1">
                <button
                  type="button"
                  class="rounded-[4px] border border-stone-200 px-2 py-1 text-2xs font-bold text-stone-600 transition-colors hover:border-ink disabled:opacity-40"
                  :disabled="ctl.busyChannelIds.value.has(channel.id)"
                  @click="ctl.toggleChannel(channel)"
                >
                  {{ channel.status === 'active' ? t('subscriptions.channels.disable') : t('subscriptions.channels.enable') }}
                </button>
                <button
                  v-if="channel.verified && channel.status === 'active'"
                  type="button"
                  class="rounded-[4px] border border-stone-200 p-1.5 text-stone-500 transition-colors hover:border-ink hover:text-ink disabled:opacity-40"
                  :title="t('subscriptions.channels.test')"
                  :disabled="ctl.busyChannelIds.value.has(channel.id)"
                  @click="ctl.sendTest(channel)"
                >
                  <Send class="h-3.5 w-3.5" />
                </button>
                <button
                  type="button"
                  class="rounded-[4px] border border-stone-200 p-1.5 text-stone-400 transition-colors hover:border-red-400 hover:text-red-600 disabled:opacity-40"
                  :title="t('subscriptions.channels.delete')"
                  :disabled="ctl.busyChannelIds.value.has(channel.id)"
                  @click="confirmRemoveChannel(channel)"
                >
                  <Trash2 class="h-3.5 w-3.5" />
                </button>
              </div>
            </li>
          </ul>
          <p v-else class="py-4 text-center text-2xs text-stone-400">
            {{ t('subscriptions.channels.empty') }}
          </p>
        </section>

        <!-- 订阅管理 -->
        <section class="stagger-enter glass-card flex flex-col gap-4 p-4" style="animation-delay: 0.1s">
          <div class="flex items-center justify-between">
            <h2 class="text-base font-bold text-stone-800">{{ t('subscriptions.subs.title') }}</h2>
            <span class="text-2xs text-stone-400">
              {{ t('subscriptions.subs.count', { count: ctl.subscriptions.value.length }) }}
            </span>
          </div>

          <form class="flex flex-col gap-2" @submit.prevent="ctl.submitSubscription">
            <div class="grid grid-cols-2 gap-2">
              <label class="flex flex-col gap-1">
                <span class="text-2xs font-bold text-stone-500">{{ t('subscriptions.subs.source') }}</span>
                <select
                  v-model="ctl.newSource.value"
                  class="rounded-[4px] border border-stone-200 bg-white px-2 py-1.5 text-sm outline-none focus:border-ink"
                >
                  <option v-for="source in SUBSCRIPTION_SOURCES" :key="source" :value="source">
                    {{ t(`subscriptions.sources.${source}`) }}
                  </option>
                </select>
              </label>
              <label class="flex flex-col gap-1">
                <span class="text-2xs font-bold text-stone-500">{{ t('subscriptions.subs.channel') }}</span>
                <select
                  v-model="ctl.newChannelId.value"
                  class="rounded-[4px] border border-stone-200 bg-white px-2 py-1.5 text-sm outline-none focus:border-ink"
                >
                  <option :value="null" disabled>{{ t('subscriptions.subs.selectChannel') }}</option>
                  <option v-for="channel in ctl.bindableChannels.value" :key="channel.id" :value="channel.id">
                    {{ channelTypeLabel(channel) }} · {{ channel.target }}
                  </option>
                </select>
              </label>
            </div>
            <p v-if="!ctl.bindableChannels.value.length" class="text-2xs text-amber-600">
              {{ t('subscriptions.subs.noBindableChannel') }}
            </p>
            <p v-else-if="subscriptionQuotaReached" class="text-2xs" style="color: var(--notice-warn-ink)">
              {{ t('subscriptions.subs.quotaHint') }}
              <RouterLink to="/membership" class="font-semibold underline underline-offset-2">
                {{ t('subscriptions.subs.quotaUpgrade') }}
              </RouterLink>
            </p>
            <button
              type="submit"
              class="self-start rounded-[4px] border border-ink bg-ink px-3 py-1.5 text-xs font-bold text-accent transition-colors hover:bg-accent hover:text-accent-ink disabled:opacity-40"
              :disabled="!ctl.canSubmitSubscription.value || subscriptionQuotaReached"
            >
              {{ t('subscriptions.subs.create') }}
            </button>
          </form>

          <SpinnerLoader v-if="ctl.loading.value && !ctl.subscriptions.value.length" class="min-h-[96px]" :size="22" />
          <ul v-else-if="ctl.subscriptions.value.length" class="flex flex-col divide-y divide-stone-100">
            <li v-for="subscription in ctl.subscriptions.value" :key="subscription.id" class="flex items-center gap-2 py-2.5">
              <div class="min-w-0 flex-1">
                <div class="flex items-center gap-1.5">
                  <span class="text-sm font-bold text-stone-800">
                    {{ t(`subscriptions.sources.${subscription.source}`) }}
                  </span>
                  <span
                    v-if="subscription.status !== 'active'"
                    class="rounded-[3px] bg-stone-100 px-1 text-[10px] font-bold text-stone-500"
                  >
                    {{ t('subscriptions.subs.paused') }}
                  </span>
                </div>
                <div class="truncate text-2xs text-stone-400" :title="subscription.target">
                  → {{ subscription.target }}
                </div>
              </div>
              <div class="flex shrink-0 items-center gap-1">
                <button
                  type="button"
                  class="rounded-[4px] border border-stone-200 px-2 py-1 text-2xs font-bold text-stone-600 transition-colors hover:border-ink disabled:opacity-40"
                  :disabled="ctl.busySubscriptionIds.value.has(subscription.id)"
                  @click="ctl.toggleSubscription(subscription)"
                >
                  {{ subscription.status === 'active' ? t('subscriptions.subs.pause') : t('subscriptions.subs.resume') }}
                </button>
                <button
                  type="button"
                  class="rounded-[4px] border border-stone-200 p-1.5 text-stone-400 transition-colors hover:border-red-400 hover:text-red-600 disabled:opacity-40"
                  :title="t('subscriptions.subs.delete')"
                  :disabled="ctl.busySubscriptionIds.value.has(subscription.id)"
                  @click="confirmRemoveSubscription(subscription)"
                >
                  <Trash2 class="h-3.5 w-3.5" />
                </button>
              </div>
            </li>
          </ul>
          <p v-else class="py-4 text-center text-2xs text-stone-400">
            {{ t('subscriptions.subs.empty') }}
          </p>
        </section>
      </div>
    </div>
  </div>
</template>
