<script setup lang="ts">
import { computed, shallowRef } from 'vue'
import { useI18n } from 'vue-i18n'
import { Bookmark } from 'lucide-vue-next'
import ReportBroadsheet, { type BroadsheetSaves, type ReportReadingMode } from '@/components/report/ReportBroadsheet.vue'
import { useSavedItems } from '@/composables/useSavedItems'
import type { BroadsheetPeek } from '@/composables/useReportPeek'
import { isSavedBriefingItem, savedBriefingSheet } from '@/features/saved/savedBriefing'
import { REPORT_TYPES } from '@/features/report/reportViewModel'

/**
 * 简报收藏（桌面大报版）：收下的条目按期排成一份大报，每期一节，节标题是「日期 · 简报名」，排法与读法照常。
 * 进来时照此刻拍一份：在这里取消的那条留在版面上、书签变空，点错了还能再收回来，离开收藏再进来才撤下。看过的不淡。
 */
defineProps<{
  mode: ReportReadingMode
  /** 宽屏右侧的论文详情栏（≥1600px）；不给就没有。 */
  peek?: BroadsheetPeek | null
}>()

const { t } = useI18n()
const saved = useSavedItems({ list: 'briefing', accept: isSavedBriefingItem })
const shown = shallowRef(saved.entries.value)

const issueTitle = (type: string, date: string) => {
  const info = REPORT_TYPES.find((report) => report.key === type)
  return t('saved.issue', { date, name: info ? t(`report.type.${info.labelKey}`) : type })
}
const built = computed(() => savedBriefingSheet(shown.value, issueTitle))

const saves: BroadsheetSaves = {
  has: (item) => {
    const entry = built.value.entryOf.get(item)
    return !!entry && saved.has(entry.id)
  },
  toggle: (item) => {
    const entry = built.value.entryOf.get(item)
    if (entry) saved.toggle(entry.id, entry.data)
  },
}
</script>

<template>
  <div v-if="shown.length" class="report-content p-5">
    <p class="report-ai-notice mb-3 inline-block rounded-full bg-stone-100 px-2.5 py-1 text-xs font-medium text-stone-500">{{ t('report.aiGeneratedNotice') }}</p>
    <ReportBroadsheet :sheet="built.sheet" :mode="mode" :generating="false" :saves="saves" :dim-read="false" :peek="peek" />
  </div>
  <div v-else class="flex h-full flex-col items-center justify-center gap-2 text-stone-400 p-4">
    <div class="flex h-12 w-12 items-center justify-center rounded-2xl bg-stone-100">
      <Bookmark class="h-6 w-6 opacity-30" />
    </div>
    <p class="text-sm font-medium text-stone-500 font-serif">{{ t('saved.emptyTitle') }}</p>
    <p class="text-xs text-center max-w-sm text-stone-400">{{ t('saved.emptyBriefingHint') }}</p>
  </div>
</template>
