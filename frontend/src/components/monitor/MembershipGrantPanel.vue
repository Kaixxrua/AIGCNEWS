<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
const { t } = useI18n()
import type {
  MembershipGrantForm,
  MembershipGrantResult,
  MembershipTier,
} from '@/features/monitor/monitorModel'
import { formatDate } from '@/features/monitor/monitorViewModel'

const props = defineProps<{
  form: MembershipGrantForm
  granting: boolean
  lastResult: MembershipGrantResult | null
}>()

const emit = defineEmits<{
  save: []
}>()

const updateForm = <K extends keyof MembershipGrantForm>(field: K, value: MembershipGrantForm[K]) => {
  // eslint-disable-next-line vue/no-mutating-props -- form 为父组件传入的草稿对象，此处为受控表单的有意回写
  props.form[field] = value
}

// 与 MastheadUser 展示口径一致：库内 member 档对外的用户组标签是 vip
const tierLabel = (tier: string) => (tier === 'member' ? 'vip' : tier)
const tierOptions: MembershipTier[] = ['member', 'free']
// 到期日期仅对 member 档有意义；free（吊销）时禁用输入，后端也会强制清空
const expiryDisabled = computed(() => props.granting || props.form.tier === 'free')
</script>

<template>
  <div class="stagger-enter glass-card shrink-0 p-5" style="animation-delay: 0.1s">
    <div class="mb-3 flex flex-wrap items-center gap-2">
      <svg class="h-4 w-4 monitor-caption" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>
      <h3 class="monitor-section-title text-sm font-semibold">{{ t('monitor.membership.title') }}</h3>
    </div>

    <p class="mb-3 text-xs leading-5 monitor-caption monitor-check-row px-3 py-2">{{ t('monitor.membership.hint') }}</p>

    <div class="grid grid-cols-1 gap-3 md:grid-cols-[minmax(220px,1.4fr)_minmax(180px,0.9fr)_minmax(150px,0.7fr)_auto] md:items-end">
      <label class="block">
        <span class="mb-1 block text-xs monitor-caption">{{ t('monitor.membership.email') }}</span>
        <input
          :value="form.email"
          type="email"
          class="input w-full py-2 text-xs"
          :placeholder="t('monitor.membership.emailPlaceholder')"
          autocomplete="off"
          :disabled="granting"
          @input="updateForm('email', ($event.target as HTMLInputElement).value.trim())"
        />
      </label>
      <label class="block">
        <span class="mb-1 block text-xs monitor-caption">{{ t('monitor.membership.tier') }}</span>
        <select
          :value="form.tier"
          class="input w-full py-2 text-xs"
          :disabled="granting"
          @change="updateForm('tier', ($event.target as HTMLSelectElement).value as MembershipTier)"
        >
          <option v-for="tier in tierOptions" :key="tier" :value="tier">
            {{ t(`monitor.membership.tierOption.${tier}`) }}
          </option>
        </select>
      </label>
      <label class="block" :title="t('monitor.membership.expiresOnHint')">
        <span class="mb-1 block text-xs monitor-caption">{{ t('monitor.membership.expiresOn') }}</span>
        <input
          :value="form.expires_on"
          type="date"
          class="input w-full py-2 text-xs"
          :disabled="expiryDisabled"
          @input="updateForm('expires_on', ($event.target as HTMLInputElement).value)"
        />
      </label>
      <div class="flex gap-2">
        <button class="monitor-btn-primary" :disabled="granting" @click="emit('save')">
          {{ t(granting ? 'monitor.saving' : 'monitor.membership.submit') }}
        </button>
      </div>
    </div>

    <p class="mt-2 text-2xs monitor-caption">{{ t('monitor.membership.expiresOnHint') }}</p>

    <div v-if="lastResult" class="mt-3 flex flex-wrap items-center gap-2 rounded-md border px-3 py-2 text-xs monitor-status-success">
      <span>{{ t('monitor.membership.lastResult') }}</span>
      <span class="badge">{{ lastResult.email }}</span>
      <span class="badge">{{ t('masthead.userGroup', { tier: tierLabel(lastResult.membership_tier) }) }}</span>
      <span v-if="lastResult.membership_expires_at" class="badge">
        {{ t('monitor.membership.expiresAt', { date: formatDate(lastResult.membership_expires_at) }) }}
      </span>
    </div>
  </div>
</template>
