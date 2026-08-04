<script setup lang="ts">
import { useI18n } from 'vue-i18n'
const { t } = useI18n()
import { BellRing } from 'lucide-vue-next'
import { REPORT_TYPES, type ReportKey } from '@/features/report/reportViewModel'

defineProps<{
  showLoginPrompt: boolean
  showSubscribePanel: boolean
  isSubscribing: boolean
  selectedSubscribeSources: ReportKey[]
  isSourceSubscribed: (source: ReportKey) => boolean
}>()

const emit = defineEmits<{
  closeLoginPrompt: []
  loginAndRedirect: []
  closeSubscribePanel: []
  toggleSubscribeSource: [source: ReportKey]
  confirmSubscribeSources: []
}>()
</script>

<template>
  <!-- 游客订阅登录提示 -->
  <div v-if="showLoginPrompt" class="rounded-2xl border p-3 shadow-sm" style="border-color: var(--notice-warn-edge); background: var(--notice-warn-bg-strong)">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <div class="flex items-center gap-2 text-sm" style="color: var(--notice-warn-ink)">
        <BellRing class="h-4 w-4 shrink-0" />
        <span>{{ t('report.loginRequired') }}</span>
      </div>
      <div class="flex items-center gap-2">
        <button class="rounded-full px-3 py-1.5 text-xs font-medium hover:bg-[var(--notice-warn-edge)]" style="color: var(--notice-warn-ink-soft)" @click="emit('closeLoginPrompt')">{{ t('report.later') }}</button>
        <button class="rounded-full bg-amber-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-amber-700" @click="emit('loginAndRedirect')">{{ t('report.goLogin') }}</button>
      </div>
    </div>
  </div>

  <!-- 日报订阅领域选择 -->
  <div v-if="showSubscribePanel" class="rounded-2xl border bg-card/90 p-3 shadow-sm" style="border-color: var(--panel-edge-info)">
    <div class="flex items-start justify-between gap-3">
      <div>
        <p class="text-sm font-semibold text-stone-700">{{ t('report.chooseDomains') }}</p>
        <p class="text-2xs text-stone-400 mt-0.5">{{ t('report.chooseDomainsHint') }}</p>
      </div>
      <button class="text-2xs text-stone-400 hover:text-stone-600" :disabled="isSubscribing" @click="emit('closeSubscribePanel')">{{ t('common.cancel') }}</button>
    </div>

    <div class="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
      <button
        v-for="type in REPORT_TYPES"
        :key="type.key"
        type="button"
        class="flex items-center gap-2 rounded-xl border px-3 py-2 text-left transition-all duration-200"
        :class="selectedSubscribeSources.includes(type.key)
          ? 'border-indigo-200 bg-indigo-50 text-indigo-800'
          : 'border-stone-100 bg-card/70 text-stone-600 hover:bg-accent-soft'"
        :disabled="isSubscribing"
        @click="emit('toggleSubscribeSource', type.key)"
      >
        <span class="flex h-4 w-4 items-center justify-center rounded border text-[10px]"
          :class="selectedSubscribeSources.includes(type.key) ? 'border-indigo-500 bg-indigo-500 text-white' : 'border-stone-300 text-transparent'">✓</span>
        <component :is="type.icon" class="h-4 w-4 shrink-0" />
        <span class="min-w-0 flex-1">
          <span class="block text-xs font-semibold">{{ t(`report.type.${type.labelKey}`) }}</span>
          <span class="block text-2xs opacity-70">{{ t(`report.type.${type.descKey}`) }}{{ isSourceSubscribed(type.key) ? ` · ${t('report.subscribed')}` : '' }}</span>
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
        :disabled="isSubscribing || !selectedSubscribeSources.length"
        @click="emit('confirmSubscribeSources')"
      >
        <span v-if="isSubscribing" class="h-3 w-3 rounded-full border-2 animate-spin" style="border-color: color-mix(in srgb, currentColor 40%, transparent); border-top-color: currentColor" />
        {{ t('report.confirmDomains', { count: selectedSubscribeSources.length }) }}
      </button>
    </div>
  </div>
</template>
