<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { CheckCircle2, Zap } from 'lucide-vue-next'
import {
  TABS,
  aiScoreDisplay,
  getModuleTags,
  getSourceConfig,
  getTabBoardStatus,
  scoreDisplay,
  tabBoardStatusHint,
  type TabKey,
  type TopDoc,
} from '@/features/dashboard/dashboardViewModel'
import type { SourceStatusMap } from '@/services/dashboard/dashboardContracts'

const props = defineProps<{
  activeTab: TabKey
  tabList: TopDoc[]
  tabLoading: boolean
  isViewingHistory: boolean
  isFinalized: boolean
  sourceStatus: SourceStatusMap
}>()

const { t } = useI18n()

const emit = defineEmits<{
  selectSource: [key: TabKey]
}>()

// 分源定稿状态（PR6）：当前 tab 按自己的源日界/定稿时刻揭榜，
// 取代整榜一刀切标签；wire 缺省（旧后端）时不渲染徽章。
const tabStatus = computed(() => getTabBoardStatus(props.sourceStatus, props.activeTab))
const tabStatusHint = computed(() =>
  tabStatus.value ? tabBoardStatusHint(tabStatus.value, t) : null,
)

// Product Hunt 榜日透出：条目 published_date 即 featuredAt 的太平洋日期，
// 与快照日可能不同（CST 上午展示的仍是 PT 昨日榜）。
const boardDateHint = computed(() => {
  if (props.activeTab !== 'producthunt') return null
  const boardDate = props.tabList.find(doc => doc.published_date)?.published_date
  return boardDate ? t('dashboard.boardDate', { date: boardDate }) : null
})
</script>

<template>
  <div class="dashboard-ranking-panel stagger-enter glass-card flex-1 min-h-0 flex flex-col overflow-hidden" style="animation-delay: 0.6s">
    <div class="flex flex-wrap items-center justify-between gap-2 px-4 py-2" style="border-bottom: 1px solid rgb(var(--stone-400-rgb) / 0.15)">
      <div class="flex flex-wrap gap-1" role="tablist" :aria-label="t('dashboard.rankingSources')">
        <button v-for="tab in TABS" :key="tab.key" class="flex items-center gap-1 rounded-full px-3 py-1 text-xs font-medium transition-all duration-200" :class="activeTab === tab.key ? 'tab-active' : 'tab-inactive'" role="tab" :aria-selected="activeTab === tab.key" @click="emit('selectSource', tab.key)">
          <component :is="tab.icon" class="h-3.5 w-3.5" />{{ t(`dashboard.stats.${tab.labelKey}`) }}
        </button>
      </div>
      <div v-if="boardDateHint || (tabStatus && tabStatusHint)" class="flex items-center gap-2">
        <span v-if="boardDateHint" class="badge bg-card text-stone-500 border border-stone-200">{{ boardDateHint }}</span>
        <span v-if="tabStatus && tabStatusHint" class="flex items-center gap-1 text-2xs" :class="tabStatus.isFinalized ? 'text-emerald-600' : 'text-amber-600'" role="status">
          <CheckCircle2 v-if="tabStatus.isFinalized" class="h-3 w-3 shrink-0" /><Zap v-else class="h-3 w-3 shrink-0" :class="tabStatus.isEmbargoed ? '' : 'animate-pulse'" />{{ tabStatusHint }}
        </span>
      </div>
    </div>

    <div v-if="!isFinalized && !tabLoading" class="flex items-center gap-2 px-4 py-1 text-xs" style="border-bottom: 1px solid var(--notice-warn-border); background: var(--notice-warn-bg)"><Zap class="h-3.5 w-3.5 animate-pulse text-amber-500"/><span class="text-stone-600">{{ t('dashboard.liveDraft') }}</span></div>
    <div v-else-if="isFinalized && !tabLoading" class="flex items-center gap-2 px-4 py-1 text-xs" style="border-bottom: 1px solid var(--notice-ok-border); background: var(--notice-ok-bg)"><CheckCircle2 class="h-3.5 w-3.5 text-emerald-500"/><span class="text-stone-400">{{ t('dashboard.finalized') }}</span></div>

    <div class="flex-1 overflow-y-auto">
      <div v-if="tabLoading" class="flex items-center justify-center py-8"><span class="inline-block h-5 w-5 rounded-full border-2 border-stone-200 border-t-stone-500 animate-spin" /></div>
      <div v-else-if="!tabList.length" class="flex flex-col items-center justify-center py-12 text-stone-400">
        <div class="w-12 h-12 mb-3 rounded-full bg-stone-100 flex items-center justify-center"><svg class="h-6 w-6 text-stone-300" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg></div>
        <p v-if="!isViewingHistory" class="text-sm font-medium text-stone-500">{{ t('dashboard.collecting') }}</p><p v-if="!isViewingHistory" class="mt-1 text-2xs text-stone-400">{{ t('dashboard.collectingHint') }}</p><p v-else class="text-sm font-medium text-stone-500">{{ t('dashboard.historyEmpty') }}</p><p v-if="isViewingHistory" class="mt-1 text-2xs text-stone-400">{{ t('dashboard.historyEmptyHint') }}</p>
      </div>
      <ol v-else>
        <li v-for="(doc, idx) in tabList" :key="idx" class="group transition-colors duration-150" :class="idx % 2 === 0 ? '' : 'bg-stone-50/50'" style="border: none">
          <a :href="doc.url || undefined" :target="doc.url ? '_blank' : undefined" :rel="doc.url ? 'noopener noreferrer' : undefined" class="flex items-start gap-2.5 px-4 py-1.5" :class="doc.url ? 'hover:bg-stone-50 cursor-pointer' : 'pointer-events-none'">
            <span class="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-2xs font-bold" :class="idx < 3 ? 'bg-ink-solid text-ink-on-solid' : 'bg-stone-100 text-stone-400'">{{ idx + 1 }}</span>
            <div class="min-w-0 flex-1">
              <div class="flex flex-wrap items-start gap-2"><p class="min-w-0 flex-1 text-sm font-medium text-stone-700 leading-tight group-hover:text-stone-900 line-clamp-2 sm:line-clamp-1" :class="doc.url ? 'group-hover:underline underline-offset-2' : ''">{{ doc.title || t('dashboard.untitled') }}</p><div class="flex shrink-0 items-center gap-1.5 ml-2"><span v-if="doc.ai_score !== undefined && doc.ai_score !== null" class="badge bg-card text-stone-600 border border-stone-200" :title="doc.ai_reason || t('dashboard.aiScore')">{{ aiScoreDisplay(doc.ai_score) }}</span><span class="badge border" :class="getSourceConfig(doc.source).badge"><span class="status-dot shrink-0" :class="getSourceConfig(doc.source).dot" />{{ getSourceConfig(doc.source).label }}</span></div></div>
              <div class="mt-0.5 flex flex-wrap items-center gap-1.5"><span class="flex items-center gap-0.5 text-2xs text-stone-500 font-medium"><component :is="scoreDisplay(doc).icon" class="h-3 w-3 shrink-0" />{{ scoreDisplay(doc).text }}</span><span v-if="doc.language" class="badge bg-card text-stone-500 border border-stone-200">{{ doc.language }}</span><span v-for="tag in getModuleTags(doc)" :key="tag" class="badge bg-card text-stone-500 border border-stone-200">{{ tag }}</span></div>
            </div>
            <svg v-if="doc.url" class="mt-1 h-3.5 w-3.5 shrink-0 text-stone-300 opacity-0 group-hover:opacity-100 transition-opacity" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>
          </a>
        </li>
      </ol>
    </div>
  </div>
</template>

<style scoped>
.tab-active { border: 1px solid var(--ink); border-radius: 4px; color: var(--projects-on-acid); background: var(--acid); box-shadow: none; }
.tab-inactive { border: 1px solid transparent; border-radius: 4px; color: var(--ink); }
.tab-inactive:hover { border-color: var(--ink); color: var(--ink); background: var(--acid-soft); }
ol > li { border-top: 1px solid var(--ink) !important; background: transparent; }
ol > li:first-child { border-top: 0 !important; }
ol > li a:hover { color: var(--ink); background: var(--acid-soft); }
ol > li a:hover :deep(.text-stone-700), ol > li a:hover :deep(.text-stone-500), ol > li a:hover :deep(.text-stone-300) { color: inherit; }
/* 榜单行内徽章紧凑化：10 条榜单一屏放下 */
:deep(.badge) { border-color: var(--ink); border-radius: 3px; background: var(--paper-light); padding: 0 5px; font-size: 10px; line-height: 16px; }
</style>
