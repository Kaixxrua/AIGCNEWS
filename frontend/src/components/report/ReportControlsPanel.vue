<script setup lang="ts">
import { useI18n } from 'vue-i18n'
const { t } = useI18n()
import { BellOff, BellRing, Mail, Pin, Send } from 'lucide-vue-next'
import {
  DAILY_ONLY_TYPES,
  PERIOD_TYPES,
  REPORT_TYPES,
  type PeriodKey,
  type ReportKey,
} from '@/features/report/reportViewModel'

type ReportTypeInfo = (typeof REPORT_TYPES)[number]
type PeriodTypeInfo = (typeof PERIOD_TYPES)[number]

defineProps<{
  currentTypeInfo?: ReportTypeInfo
  currentPeriodInfo?: PeriodTypeInfo
  selectedType: ReportKey
  selectedPeriod: PeriodKey
  selectedDate: string
  isCached: boolean
  isGenerating: boolean
  isLoggedIn: boolean
  isAdmin: boolean
  isCurrentSubscribed: boolean
  isSubscribing: boolean
  isSendingEmail: boolean
  emailSentMsg: string
  reportContent: string
  autoScroll: boolean
  isPeriodDisabled: (periodKey: PeriodKey) => boolean
}>()

const emit = defineEmits<{
  'update:selectedType': [value: ReportKey]
  'update:selectedPeriod': [value: PeriodKey]
  'update:selectedDate': [value: string]
  toggleSubscribe: []
  promptLoginForSubscribe: []
  sendToEmail: []
  manageSubscriptions: []
  generate: []
}>()
</script>

<template>
  <!-- 第一行：标题 + 状态 + 操作按钮 -->
  <div class="flex flex-wrap items-center justify-between gap-3">
    <div class="flex items-center gap-2 min-w-0">
      <component v-if="currentTypeInfo?.icon" :is="currentTypeInfo.icon" class="h-5 w-5 text-stone-500 shrink-0" />
      <h1 class="text-lg font-bold text-stone-800 tracking-tight font-serif truncate">{{ currentTypeInfo ? t(`report.type.${currentTypeInfo.labelKey}`) : t('report.titleFallback') }}</h1>
      <span class="text-xs text-stone-400 hidden sm:inline">{{ selectedDate }} · {{ currentPeriodInfo ? t(`report.period.${currentPeriodInfo.key}`) : '' }} · {{ currentTypeInfo ? t(`report.type.${currentTypeInfo.descKey}`) : '' }}</span>
    </div>
    <div class="flex w-full flex-wrap items-center gap-2 sm:w-auto sm:shrink-0">
      <div v-if="isCached && !isGenerating" class="flex items-center gap-1 rounded-full bg-green-50 px-2.5 py-1 border border-green-200">
        <span class="status-dot bg-brand-green" />
        <span class="text-2xs font-medium text-green-700">{{ t('report.cached') }}</span>
      </div>
      <div v-if="isGenerating" class="stream-indicator">
        <span class="stream-dot" />
        <span>{{ t('report.generating') }}</span>
      </div>

      <!-- 订阅/取消订阅按钮 -->
      <button
        class="flex items-center gap-1 rounded-full px-2.5 py-1 text-2xs font-medium transition-all duration-200"
        :class="isCurrentSubscribed
          ? 'bg-amber-50 text-amber-700 border border-amber-200 hover:bg-amber-100'
          : 'bg-indigo-50 text-indigo-700 border border-indigo-200 hover:bg-indigo-100'"
        :disabled="isSubscribing"
        @click="isLoggedIn ? emit('toggleSubscribe') : emit('promptLoginForSubscribe')"
      >
        <span v-if="isSubscribing" class="h-3 w-3 rounded-full border-2 border-current/40 border-t-current animate-spin" />
        <BellOff v-else-if="isCurrentSubscribed" class="h-3 w-3" />
        <BellRing v-else class="h-3 w-3" />
        {{ t(isCurrentSubscribed ? 'report.unsubscribe' : 'report.subscribe') }}
      </button>

      <!-- 发送到邮箱 -->
      <button
        v-if="isLoggedIn && isCached && reportContent"
        class="flex items-center gap-1 rounded-full px-2.5 py-1 text-2xs font-medium bg-stone-50 text-stone-600 border border-stone-200 hover:bg-stone-100 transition-all duration-200"
        :disabled="isSendingEmail"
        @click="emit('sendToEmail')"
      >
        <span v-if="isSendingEmail" class="h-3 w-3 rounded-full border-2 border-stone-400/40 border-t-stone-500 animate-spin" />
        <Send v-else class="h-3 w-3" />
        {{ t('report.sendBriefing') }}
      </button>

      <!-- 操作成功提示 -->
      <span v-if="emailSentMsg" class="inline-flex items-center gap-1 rounded-full border border-green-200 bg-green-50 px-2.5 py-1 text-2xs font-medium text-green-700">
        <Mail class="h-3 w-3" />
        {{ emailSentMsg }}
      </span>

      <button
        v-if="isLoggedIn"
        class="flex items-center gap-1 rounded-full px-2.5 py-1 text-2xs font-medium bg-stone-50 text-stone-600 border border-stone-200 hover:bg-stone-100 transition-all duration-200"
        :disabled="isSubscribing"
        @click="emit('manageSubscriptions')"
      >
        <BellRing class="h-3 w-3" />
        {{ t('report.manageSubscriptions') }}
      </button>

      <!-- Admin: 生成相关控件 -->
      <template v-if="isAdmin">
        <span v-if="isGenerating" class="flex items-center gap-1 text-2xs" :class="autoScroll ? 'text-cyan-600' : 'text-stone-400'">
          <span class="status-dot" :class="autoScroll ? 'bg-cyan-500 animate-[pulseDot_2s_ease-in-out_infinite]' : 'bg-stone-400'" />
          {{ t(autoScroll ? 'report.following' : 'report.unlocked') }}
        </span>
        <button class="btn-primary gap-1.5 text-xs py-1.5 px-3" :disabled="isGenerating" @click="emit('generate')">
          <span v-if="isGenerating" class="h-3 w-3 rounded-full border-2 border-white/40 border-t-white animate-spin" />
          <svg v-else class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"/></svg>
          {{ isGenerating ? t('report.generating') : t(isCached ? 'report.regenerate' : 'report.generate') }}
        </button>
      </template>
    </div>
  </div>

  <!-- 第二行：源选择 + 周期选择 -->
  <div class="flex flex-wrap items-center gap-2" style="border-top: 1px solid rgba(168,162,158,0.10); padding-top: 8px">
    <div class="flex max-w-full flex-nowrap gap-1.5 overflow-x-auto pb-1 sm:flex-wrap sm:overflow-visible">
      <button
        v-for="type in REPORT_TYPES"
        :key="type.key"
        class="flex shrink-0 items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium transition-all duration-200"
        :class="selectedType === type.key
          ? 'tab-active shadow-sm'
          : 'tab-inactive'"
        :style="selectedType !== type.key ? 'background: rgba(255,255,255,0.6); border: 1px solid rgba(168,162,158,0.20)' : ''"
        :disabled="isGenerating"
        @click="emit('update:selectedType', type.key)"
      >
        <component :is="type.icon" class="h-3 w-3 shrink-0" />
        <span>{{ t(`report.type.${type.labelKey}`) }}</span>
      </button>
    </div>

    <span class="text-stone-200">|</span>

    <div class="flex items-center gap-1">
      <button
        v-for="p in PERIOD_TYPES"
        :key="p.key"
        class="rounded-full px-3 py-1 text-xs font-medium transition-all duration-200"
        :class="[
          isPeriodDisabled(p.key) ? 'cursor-not-allowed opacity-30 text-stone-400'
            : selectedPeriod === p.key ? 'bg-cyan-50 text-cyan-700 font-semibold border border-cyan-200'
            : 'text-stone-400 hover:bg-accent-soft hover:text-stone-600'
        ]"
        :disabled="isGenerating || isPeriodDisabled(p.key)"
        @click="!isPeriodDisabled(p.key) && emit('update:selectedPeriod', p.key)"
      >{{ t(`report.period.${p.key}`) }}</button>
      <span v-if="DAILY_ONLY_TYPES.has(selectedType)" class="flex items-center gap-0.5 text-2xs text-stone-400 ml-0.5">
        <Pin class="h-2.5 w-2.5 shrink-0" />
        {{ t('report.dailyOnly') }}
      </span>
    </div>

    <!-- Admin: 日期选择 -->
    <div v-if="isAdmin" class="flex items-center gap-1 ml-2">
      <input :value="selectedDate" type="date" class="input w-auto py-1 text-xs" :disabled="isGenerating" @input="emit('update:selectedDate', ($event.target as HTMLInputElement).value)" />
    </div>
  </div>
</template>
