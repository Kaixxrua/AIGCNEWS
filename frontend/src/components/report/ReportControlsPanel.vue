<script setup lang="ts">
import { ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
const { t } = useI18n()
import { BellRing, Bookmark, Mail, Send } from 'lucide-vue-next'
import { vIndicator } from '@/motion/indicator'
import RollText from '@/motion/RollText.vue'
import type { ReportReadingMode } from '@/components/report/ReportBroadsheet.vue'
import {
  REPORT_TYPES,
  todayInReportTimeZone,
  type ReportKey,
} from '@/features/report/reportViewModel'

type ReportTypeInfo = (typeof REPORT_TYPES)[number]

const props = defineProps<{
  currentTypeInfo?: ReportTypeInfo
  selectedType: ReportKey
  selectedDate: string
  isCached: boolean
  isGenerating: boolean
  isLoggedIn: boolean
  isAdmin: boolean
  isSubscribing: boolean
  isSendingEmail: boolean
  emailSentMsg: string
  rssSubscribed: boolean
  emailSubscribed: boolean
  userEmail: string
  isRssBusy: boolean
  reportContent: string
  autoScroll: boolean
  /** 桌面大报版式的阅读方式；不传则不显示切换。 */
  readingMode?: ReportReadingMode | null
  /** 本机收了几条简报条目（桌面大报版）；不给就没有「收藏」标签。 */
  savedCount?: number | null
  /** 正在看收藏：分区标签里亮「收藏」，这一期的操作（缓存状态、发送到邮箱、生成）收起。 */
  savedView?: boolean
}>()

const emit = defineEmits<{
  'update:selectedType': [value: ReportKey]
  'update:selectedDate': [value: string]
  toggleSubscribe: []
  promptLoginForSubscribe: []
  sendToEmail: []
  copySubscribedRss: []
  generate: []
  'update:readingMode': [value: ReportReadingMode]
  'update:savedView': [value: boolean]
}>()

// 日期框只能选到今天（CST）：简报按天生成，之后的日子还没有
const today = todayInReportTimeZone()

// 收藏条数换值时滚动，多了新数字自下而上，少了自上而下
const savedDirection = ref<1 | -1>(1)
watch(() => props.savedCount ?? 0, (count, previous) => { savedDirection.value = count < previous ? -1 : 1 }, { flush: 'sync' })
</script>

<template>
  <!-- 第一行：标题 + 状态 + 操作按钮 -->
  <div class="report-controls__head flex flex-wrap items-center justify-between gap-3">
    <div class="flex items-center gap-2 min-w-0">
      <template v-if="savedView">
        <Bookmark class="h-5 w-5 text-stone-500 shrink-0" />
        <h1 class="report-controls__title comic-title text-lg font-bold text-stone-800 tracking-tight font-serif truncate">{{ t('saved.title') }}</h1>
        <span class="report-controls__meta text-xs text-stone-400 hidden sm:inline">{{ t('saved.count', { count: savedCount ?? 0 }) }} · {{ t('saved.localNote') }}</span>
      </template>
      <template v-else>
        <component v-if="currentTypeInfo?.icon" :is="currentTypeInfo.icon" class="h-5 w-5 text-stone-500 shrink-0" />
        <h1 class="report-controls__title comic-title text-lg font-bold text-stone-800 tracking-tight font-serif truncate">{{ currentTypeInfo ? t(`report.type.${currentTypeInfo.labelKey}`) : t('report.titleFallback') }}</h1>
        <span class="report-controls__meta text-xs text-stone-400 hidden sm:inline">{{ selectedDate }} · {{ t('report.period.daily') }} · {{ currentTypeInfo ? t(`report.type.${currentTypeInfo.descKey}`) : '' }}</span>
      </template>
      <!-- 桌面版把 AI 生成声明接在日期之后，同一行 -->
      <p v-if="reportContent || savedView" class="report-ai-bubble">{{ t('report.aiGeneratedNotice') }}</p>
      <!-- 桌面大报版式的阅读方式：全文 / 导读，排在日期行末 -->
      <div
        v-if="readingMode && (reportContent || savedView)"
        v-indicator="{ active: '[aria-pressed=true]' }"
        class="report-reading-mode"
        role="group"
        :aria-label="t('report.readingMode.label')"
      >
        <button
          v-for="mode in (['full', 'lead'] as const)"
          :key="mode"
          type="button"
          :aria-pressed="readingMode === mode"
          :disabled="isGenerating"
          @click="emit('update:readingMode', mode)"
        >
          {{ t(`report.readingMode.${mode}`) }}
        </button>
      </div>
    </div>
    <div class="report-controls__actions flex min-w-0 flex-wrap items-center gap-2 sm:shrink-0">
      <div v-if="!isGenerating && !savedView" class="report-cache-chip flex items-center gap-1 rounded-full bg-green-50 px-2.5 py-1 border border-green-200" :class="{ 'is-pending': !isCached }">
        <span class="status-dot bg-brand-green" />
        <span class="text-2xs font-medium text-green-700">{{ t('report.cached') }}</span>
      </div>
      <div v-if="isGenerating" class="stream-indicator">
        <span class="stream-dot" />
        <span>{{ t('report.generating') }}</span>
      </div>

      <button
        v-if="rssSubscribed"
        type="button"
        class="flex items-center gap-1 rounded-full bg-emerald-50 px-2.5 py-1 text-2xs font-medium text-emerald-700 border border-emerald-200 hover:bg-emerald-100 disabled:cursor-wait disabled:opacity-60"
        :disabled="isRssBusy"
        :title="t('report.wizard.copySubscribedRss')"
        @click="emit('copySubscribedRss')"
      >
        <span v-if="isRssBusy" class="h-3 w-3 rounded-full border-2 border-current/40 border-t-current animate-spin" />
        <span v-else class="status-dot bg-brand-green" />
        {{ t('report.wizard.subscribedRss') }}
      </button>
      <span v-if="emailSubscribed" class="flex items-center gap-1 rounded-full bg-emerald-50 px-2.5 py-1 text-2xs font-medium text-emerald-700 border border-emerald-200" :title="t('report.wizard.subscribedEmail', { email: userEmail })">
        <Mail class="h-3 w-3" />
        {{ t('report.wizard.subscribedEmail', { email: userEmail }) }}
      </span>

      <!-- 订阅按钮 -->
      <button data-tour="subscribe"
        class="flex items-center gap-1 rounded-full px-2.5 py-1 text-2xs font-medium transition-all duration-200 bg-indigo-50 text-indigo-700 border border-indigo-200 hover:bg-indigo-100"
        :disabled="isSubscribing"
        @click="isLoggedIn ? emit('toggleSubscribe') : emit('promptLoginForSubscribe')"
      >
        <span v-if="isSubscribing" class="h-3 w-3 rounded-full border-2 border-current/40 border-t-current animate-spin" />
        <BellRing v-else class="h-3 w-3" />
        {{ t('report.subscribe') }}
      </button>

      <!-- 发送到邮箱 -->
      <button
        v-if="isLoggedIn && isCached && reportContent && !savedView"
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

      <!-- Admin: 生成相关控件 -->
      <template v-if="isAdmin && !savedView">
        <span v-if="isGenerating" class="flex items-center gap-1 text-2xs" :class="autoScroll ? 'text-cyan-600' : 'text-stone-400'">
          <span class="status-dot" :class="autoScroll ? 'bg-cyan-500 animate-[pulseDot_2s_ease-in-out_infinite]' : 'bg-stone-400'" />
          {{ t(autoScroll ? 'report.following' : 'report.unlocked') }}
        </span>
        <button class="btn-primary gap-1.5 text-xs py-1.5 px-3" :disabled="isGenerating" @click="emit('generate')">
          <span v-if="isGenerating" class="h-3 w-3 rounded-full border-2 animate-spin" style="border-color: color-mix(in srgb, currentColor 40%, transparent); border-top-color: currentColor" />
          <svg v-else class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"/></svg>
          {{ isGenerating ? t('report.generating') : t(isCached ? 'report.regenerate' : 'report.generate') }}
        </button>
      </template>
    </div>
  </div>

  <!-- 第二行：源选择 + 日期选择 -->
  <div class="report-controls__tabs flex flex-wrap items-center gap-2" style="border-top: 1px solid rgb(var(--stone-400-rgb) / 0.1); padding-top: 8px">
    <!-- 每个类型签都有自己的框，换选中时不滑块，新选中的签盖章式弹入。 -->
    <div v-indicator="{ active: '.tab-active', mark: false, pop: true }" class="flex max-w-full flex-nowrap gap-1.5 overflow-x-auto pb-1 sm:flex-wrap sm:overflow-visible">
      <button
        v-for="type in REPORT_TYPES"
        :key="type.key"
        class="comic-chip flex shrink-0 items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium transition-all duration-200"
        :class="!savedView && selectedType === type.key
          ? 'tab-active is-active shadow-sm'
          : 'tab-inactive'"
        :style="savedView || selectedType !== type.key ? 'background: rgb(var(--card-rgb) / 0.6); border: 1px solid rgb(var(--stone-400-rgb) / 0.2)' : ''"
        :disabled="isGenerating"
        @click="emit('update:selectedType', type.key)"
      >
        <component :is="type.icon" class="h-3 w-3 shrink-0" />
        <span>{{ t(`report.type.${type.labelKey}`) }}</span>
      </button>
      <!-- 收藏：排在分区标签最后，桌面才有、一直在（没收过时点进去说怎么收），带着收了几条；点它看收下的条目 -->
      <button
        v-if="savedCount != null"
        type="button"
        class="comic-chip report-saved-tab flex shrink-0 items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium transition-all duration-200"
        :class="savedView ? 'tab-active is-active shadow-sm' : 'tab-inactive'"
        :style="!savedView ? 'background: rgb(var(--card-rgb) / 0.6); border: 1px solid rgb(var(--stone-400-rgb) / 0.2)' : ''"
        :aria-pressed="savedView"
        :disabled="isGenerating"
        @click="emit('update:savedView', true)"
      >
        <Bookmark class="h-3 w-3 shrink-0" />
        <span>{{ t('saved.title') }}</span>
        <span class="report-saved-tab__count"><RollText :value="savedCount" :direction="savedDirection" /></span>
      </button>
    </div>

    <!-- Admin: 日期选择 -->
    <div v-if="isAdmin" class="flex items-center gap-1 ml-2">
      <input :value="selectedDate" type="date" :max="today" class="input w-auto py-1 text-xs" :disabled="isGenerating" @input="emit('update:selectedDate', ($event.target as HTMLInputElement).value)" />
    </div>
  </div>
</template>

<style scoped>
.report-ai-bubble { display: none; }
/* 「已缓存」随简报一起到：手机和平板上先隐身占好位置，免得那时操作区才换行、把分区签和正文往下推；
   桌面大报版按实际有的按钮排版，没缓存时照旧不占位。 */
.report-cache-chip.is-pending { visibility: hidden; }
@media (min-width: 1024px) { .report-cache-chip.is-pending { display: none; } }
</style>
