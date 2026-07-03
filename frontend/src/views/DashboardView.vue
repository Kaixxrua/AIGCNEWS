<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useTransition, TransitionPresets } from '@vueuse/core'
import { useRouter } from 'vue-router'
import { api, fetchSnapshotDates } from '../services/api'
import GlassCalendar from '../components/GlassCalendar.vue'
import {
  FileText, Code2, Newspaper, Rocket, Circle,
  Star, Heart, ThumbsUp, ArrowUp, Flame,
  CalendarDays, RefreshCw, Zap, CheckCircle2,
} from 'lucide-vue-next'

const router = useRouter()

interface TopDoc {
  id?: number | string
  title?: string
  summary?: string
  score?: number
  raw_score?: number
  published_at?: string
  published_date?: string
  created_at?: string
  snapshot_date?: string
  source?: string
  url?: string
  stars?: number
  language?: string
  feed_name?: string
  ai_score?: number
  ai_reason?: string
  likes?: number
  downloads?: number
  pipeline_tag?: string
  source_channel?: string
  tags?: string[]
  votes?: number
}

interface Stats {
  total_documents?: number
  source_counts?: Record<string, number>
  registered_users?: number
  today_registered_users?: number
  user_count?: number
  today_new_documents?: number
  today_unique_visitors?: number
}

const MODULE_KEYWORDS: Record<string, string[]> = {
  '大模型': ['llm', 'language model', 'gpt', 'llama', 'qwen', 'mistral', 'gemma', 'deepseek', 'moe', 'transformer', 'reasoning'],
  '智能体': ['agent', 'multi-agent', 'autonomous', 'tool use', 'planning', 'workflow', 'orchestration'],
  '多模态': ['multimodal', 'vision', 'vlm', 'image', 'video', 'audio', 'speech', 'ocr'],
  '评测':   ['benchmark', 'evaluation', 'dataset', 'alignment', 'safety'],
  '工程':   ['inference', 'serving', 'quantization', 'distillation', 'vllm', 'edge', 'deployment'],
  'RAG':    ['rag', 'retrieval', 'vector', 'embedding', 'knowledge'],
}

const TABS = [
  { key: 'arxiv',       label: 'Papers',   icon: FileText,   color: 'brand-blue' },
  { key: 'github',      label: 'Code',     icon: Code2,      color: 'ink' },
  { key: 'news',        label: 'News',     icon: Newspaper,  color: 'brand-amber' },
  { key: 'producthunt', label: 'Products', icon: Rocket,     color: 'brand-rose' },
  { key: 'hackernews',  label: 'HN',       icon: Circle,     color: 'brand-amber' },
] as const

const PERIODS = [
  { key: 'daily',   label: '日榜' },
  { key: 'weekly',  label: '周榜' },
  { key: 'monthly', label: '月榜' },
] as const

const DAILY_ONLY_TABS = new Set(['news', 'producthunt', 'hackernews'])

type TabKey    = (typeof TABS)[number]['key']
type PeriodKey = (typeof PERIODS)[number]['key']

const activeTab    = ref<TabKey>('arxiv')
const activePeriod = ref<PeriodKey>('daily')

const isPeriodDisabled = (periodKey: PeriodKey): boolean =>
  periodKey !== 'daily' && DAILY_ONLY_TABS.has(activeTab.value)

const tabList  = ref<TopDoc[]>([])
const stats    = ref<Stats>({})
const loading  = ref(true)
const tabLoading = ref(false)
const errorMsg = ref('')

// AbortController：每次切换 Tab / Period / Date 时取消上一个未完成的请求，防止竞态覆盖
let _abortController: AbortController | null = null

function _newAbortSignal(): AbortSignal {
  if (_abortController) _abortController.abort()
  _abortController = new AbortController()
  return _abortController.signal
}

const _d = new Date()
const todayStr = `${_d.getFullYear()}-${String(_d.getMonth() + 1).padStart(2, '0')}-${String(_d.getDate()).padStart(2, '0')}`
const currentDate = ref<string>(todayStr)

const availableDates = ref<string[]>([])

const isViewingHistory = computed(() => currentDate.value !== todayStr)
const isFinalized = ref(false)
const isEmbargoed = ref(false)

const fetchDashboardData = async (tab: TabKey, period: PeriodKey, date?: string, signal?: AbortSignal) => {
  const dateParam = date || currentDate.value
  const [summaryRes, topRes] = await Promise.all([
    api.get('/dashboard/summary', { params: { period, date: dateParam }, signal }),
    api.get('/dashboard/top', { params: { limit: 10, source: tab, period, date: dateParam }, signal }),
  ])
  stats.value   = summaryRes.data.stats ?? {}
  tabList.value = topRes.data.items ?? []
  isFinalized.value = summaryRes.data.is_finalized ?? false
  isEmbargoed.value = summaryRes.data.is_embargoed ?? false
}

const fetchAvailableDates = async () => {
  try {
    availableDates.value = await fetchSnapshotDates(90)
  } catch (e) {
    console.warn('[Dashboard] 获取快照日期失败', e)
  }
}

// 单独获取用户数指标（不缓存接口，实时读取数据库）
const fetchUserCountMetric = async () => {
  try {
    const res = await api.get('/dashboard/visitor-count')
    stats.value = {
      ...stats.value,
      registered_users: res.data.registered_users ?? stats.value.registered_users ?? 0,
      today_registered_users: res.data.today_registered_users ?? 0,
      user_count: res.data.user_count ?? 0,
    }
    // 同步更新用户数动画数据源
    visitorSources.value = visitorCards.map(card => {
      const key = card.key as keyof typeof stats.value
      return Number(stats.value[key] ?? 0)
    })
  } catch (e) {
    console.warn('[Dashboard] 获取用户数失败', e)
  }
}

onMounted(async () => {
  try {
    await Promise.all([
      fetchDashboardData(activeTab.value, activePeriod.value, currentDate.value),
      fetchAvailableDates(),
      fetchUserCountMetric(),
    ])
  } catch (e) {
    errorMsg.value = String(e)
  } finally {
    loading.value = false
    updateStatSources()
  }
})

watch(activeTab, (tab) => {
  if (DAILY_ONLY_TABS.has(tab) && activePeriod.value !== 'daily') {
    activePeriod.value = 'daily'
  }
})

watch([activeTab, activePeriod], async ([tab, period]) => {
  tabLoading.value = true
  tabList.value = []  // 切换时立即清空，避免旧数据残留
  const signal = _newAbortSignal()
  try {
    await fetchDashboardData(tab, period, currentDate.value, signal)
    updateStatSources()
  } catch (e: any) {
    if (e?.name === 'CanceledError' || e?.code === 'ERR_CANCELED') return  // 被新请求取消，静默忽略
    console.error('Failed to load dashboard data', e)
  } finally {
    tabLoading.value = false
  }
})

const onDateChange = async (date: string) => {
  currentDate.value = date
  tabLoading.value = true
  tabList.value = []  // 切换时立即清空
  countUpDisabled.value = true
  const signal = _newAbortSignal()
  try {
    await fetchDashboardData(activeTab.value, activePeriod.value, date, signal)
    updateStatSources()
  } catch (e: any) {
    if (e?.name === 'CanceledError' || e?.code === 'ERR_CANCELED') return
    console.error('Failed to load dashboard data by date', e)
  } finally {
    tabLoading.value = false
  }
}

const getModuleTags = (doc: TopDoc): string[] => {
  const text = ((doc.title || '') + ' ' + (doc.summary || '')).toLowerCase()
  const tags: string[] = []
  for (const [tag, keywords] of Object.entries(MODULE_KEYWORDS)) {
    if (keywords.some(kw => text.includes(kw))) tags.push(tag)
  }
  return tags.slice(0, 3)
}

// 来源配置表（暖调去色极简）
const SOURCE_CONFIG: Record<string, { label: string; dot: string; badge: string }> = {
  github:      { label: 'GitHub',  dot: 'bg-stone-400',  badge: 'bg-white text-stone-600 border border-stone-200' },
  arxiv:       { label: 'Arxiv',   dot: 'bg-stone-400',  badge: 'bg-white text-stone-600 border border-stone-200' },
  news:        { label: 'News',    dot: 'bg-stone-400',  badge: 'bg-white text-stone-600 border border-stone-200' },
  huggingface: { label: 'HF',      dot: 'bg-stone-400',  badge: 'bg-white text-stone-600 border border-stone-200' },
  producthunt: { label: 'PH',      dot: 'bg-stone-400',  badge: 'bg-white text-stone-600 border border-stone-200' },
  hackernews:  { label: 'HN',      dot: 'bg-stone-400',  badge: 'bg-white text-stone-600 border border-stone-200' },
}

const getSourceConfig = (src?: string) =>
  SOURCE_CONFIG[src || ''] ?? { label: src || '?', dot: 'bg-stone-300', badge: 'bg-white text-stone-500 border border-stone-200' }

const docDateDisplay = (doc: TopDoc): { label: string; title: string } => {
  const pub     = doc.published_date || doc.published_at || ''
  const snapshotDate = doc.snapshot_date || ''
  if (doc.source === 'arxiv') {
    if (snapshotDate) {
      return { label: snapshotDate, title: `论文发表于: ${pub.slice(0, 16).replace('T', ' ')}` }
    }
    const created = doc.created_at || ''
    return {
      label: created ? `采集: ${created.slice(0, 10)}` : pub.slice(0, 10),
      title: pub ? `论文发表于: ${pub.slice(0, 16).replace('T', ' ')}` : '',
    }
  }
  return { label: pub.slice(0, 16).replace('T', ' '), title: '' }
}

const aiScoreDisplay = (score?: number) => {
  if (score === undefined || score === null) return null
  return `${score}/10`
}

// 返回 { icon, text } 用于模板中显示图标组件 + 文字
const scoreDisplay = (doc: TopDoc): { icon: any; text: string } => {
  if (doc.source === 'github')      return { icon: Star,     text: `${doc.stars ?? Math.round(doc.raw_score ?? doc.score ?? 0)}` }
  if (doc.source === 'huggingface') return { icon: Heart,    text: `${Math.round(doc.raw_score ?? doc.likes ?? doc.score ?? 0)}` }
  if (doc.source === 'news')        return { icon: Newspaper, text: `${doc.feed_name || '新闻'}` }
  if (doc.source === 'producthunt') return { icon: ThumbsUp, text: `${Math.round(doc.raw_score ?? doc.votes ?? doc.score ?? 0)} votes` }
  if (doc.source === 'hackernews')  return { icon: ArrowUp,  text: `${Math.round(doc.raw_score ?? doc.score ?? 0)} pts` }
  return { icon: Flame, text: `${Math.round(doc.raw_score ?? doc.score ?? 0)}` }
}

// 统计卡片数据（彩色图标 + 彩色数字）
const statCards = [
  {
    label: 'Total', key: 'total', dark: true,
    iconBg: 'bg-white/10', iconColor: 'text-gray-300', numColor: 'text-white',
    cardBg: 'bg-slate-800 border-slate-700',
    labelColor: 'text-slate-300',
    icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 014 10 15.3 15.3 0 01-4 10 15.3 15.3 0 01-4-10 15.3 15.3 0 014-10z"/></svg>`,
  },
  {
    label: 'Papers', key: 'arxiv', dark: false,
    iconBg: 'bg-blue-50', iconColor: 'text-blue-500', numColor: 'text-blue-600',
    icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14,2 14,8 20,8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>`,
  },
  {
    label: 'GitHub', key: 'github', dark: false,
    iconBg: 'bg-gray-100', iconColor: 'text-gray-600', numColor: 'text-gray-800',
    icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M9 19c-5 1.5-5-2.5-7-3m14 6v-3.87a3.37 3.37 0 00-.94-2.61c3.14-.35 6.44-1.54 6.44-7A5.44 5.44 0 0020 4.77 5.07 5.07 0 0019.91 1S18.73.65 16 2.48a13.38 13.38 0 00-7 0C6.27.65 5.09 1 5.09 1A5.07 5.07 0 005 4.77a5.44 5.44 0 00-1.5 3.78c0 5.42 3.3 6.61 6.44 7A3.37 3.37 0 009 18.13V22"/></svg>`,
  },
  {
    label: 'News', key: 'news', dark: false,
    iconBg: 'bg-amber-50', iconColor: 'text-amber-500', numColor: 'text-amber-600',
    icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M4 22h16a2 2 0 002-2V4a2 2 0 00-2-2H8a2 2 0 00-2 2v16a2 2 0 01-2 2zm0 0a2 2 0 01-2-2v-9c0-1.1.9-2 2-2h2"/><line x1="10" y1="6" x2="18" y2="6"/><line x1="10" y1="10" x2="18" y2="10"/><line x1="10" y1="14" x2="14" y2="14"/></svg>`,
  },
  {
    label: 'Products', key: 'producthunt', dark: false,
    iconBg: 'bg-rose-50', iconColor: 'text-rose-500', numColor: 'text-rose-600',
    icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M21 16V8a2 2 0 00-1-1.73l-7-4a2 2 0 00-2 0l-7 4A2 2 0 003 8v8a2 2 0 001 1.73l7 4a2 2 0 002 0l7-4A2 2 0 0021 16z"/></svg>`,
  },
  {
    label: 'HN', key: 'hackernews', dark: false,
    iconBg: 'bg-orange-50', iconColor: 'text-orange-500', numColor: 'text-orange-500',
    icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"/></svg>`,
  },
]

const visitorCards = [
  {
    label: '用户数', key: 'user_count', dark: false,
    iconBg: 'bg-purple-50', iconColor: 'text-purple-500', numColor: 'text-purple-600',
    icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M17 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 00-3-3.87"/><path d="M16 3.13a4 4 0 010 7.75"/></svg>`,
  },
  {
    label: '新增文档数', key: 'today_new_documents', dark: false,
    iconBg: 'bg-teal-50', iconColor: 'text-teal-500', numColor: 'text-teal-600',
    icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="12" y1="18" x2="12" y2="12"/><line x1="9" y1="15" x2="15" y2="15"/></svg>`,
  },
]

const getStatValue = (key: string): number => {
  if (key === 'total') return Number(stats.value.total_documents ?? 0)
  return Number(stats.value.source_counts?.[key] ?? 0)
}

const countUpDisabled = ref(false)
const statSources = ref(statCards.map(() => 0))

const animatedStats = statCards.map((_, i) => {
  const source = computed(() => statSources.value[i])
  return useTransition(source, {
    duration: 1000,
    transition: TransitionPresets.easeOutCubic,
    disabled: countUpDisabled,
  })
})

const visitorSources = ref(visitorCards.map(() => 0))

const animatedVisitors = visitorCards.map((_, i) => {
  const source = computed(() => visitorSources.value[i])
  return useTransition(source, {
    duration: 1200,
    transition: TransitionPresets.easeOutCubic,
    disabled: countUpDisabled,
  })
})

const updateStatSources = () => {
  statSources.value = statCards.map(card => getStatValue(card.key))
  visitorSources.value = visitorCards.map(card => {
    const key = card.key as keyof typeof stats.value
    return Number(stats.value[key] ?? 0)
  })
}

const getAnimatedValue = (index: number): string => {
  const transition = animatedStats[index]
  const val = transition ? transition.value : 0
  return Math.round(val ?? 0).toString()
}

const getVisitorAnimatedValue = (index: number): string => {
  const transition = animatedVisitors[index]
  const val = transition ? transition.value : 0
  return Math.round(val ?? 0).toLocaleString()
}

const getUserCountParts = (): string => {
  const registered = Number(stats.value.registered_users ?? 0).toLocaleString()
  const todayRegistered = Number(stats.value.today_registered_users ?? 0).toLocaleString()
  return `${registered}+${todayRegistered}`
}

const getVisitorDisplayValue = (cardKey: string, index: number): string => {
  if (cardKey === 'user_count') return getUserCountParts()
  return getVisitorAnimatedValue(index)
}

const hasData = computed(() => {
  const total = Number(stats.value.total_documents ?? 0)
  return total > 0 || tabList.value.length > 0
})
</script>

<template>
  <div class="flex h-full flex-col gap-2 overflow-y-auto px-6 py-3 pb-16">

    <!-- 页头 — 简洁标题 -->
    <div class="stagger-enter flex items-center justify-between shrink-0">
      <h1 class="text-xl font-semibold text-stone-800 tracking-tight font-serif">Dashboard</h1>
      <div v-if="!loading && isViewingHistory" class="flex items-center gap-1.5 text-xs text-stone-400">
        <CalendarDays class="h-3.5 w-3.5" />
        <span class="text-stone-700 font-medium">{{ currentDate }}</span>
      </div>
    </div>

    <!-- 错误提示 -->
    <div
      v-if="errorMsg"
      class="shrink-0 glass-card flex items-center gap-2 px-5 py-3 text-sm text-rose-600"
    >
      <svg class="h-4 w-4 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/>
      </svg>
      {{ errorMsg }}
    </div>

    <!-- 顶部区域：统计卡片 + 日历 -->
    <div v-if="loading" class="flex items-start gap-2 shrink-0">
      <div class="flex-1 flex flex-col gap-2">
        <div class="grid gap-2 grid-cols-3">
          <div v-for="i in 6" :key="i" class="glass-card h-[44px] animate-pulse" />
        </div>
        <div class="grid gap-2 grid-cols-2">
          <div v-for="i in 2" :key="'v'+i" class="glass-card h-[44px] animate-pulse" />
        </div>
      </div>
      <div class="w-[170px] shrink-0 glass-card h-[150px] animate-pulse" />
    </div>

    <div v-else class="flex items-start gap-2 shrink-0">
      <div class="flex-1 flex flex-col gap-2">
        <!-- 6 个数据源卡片 -->
        <div class="grid gap-2 grid-cols-3">
          <div
            v-for="(card, index) in statCards"
            :key="card.key"
            class="stagger-enter h-[44px] px-2.5 flex items-center justify-between transition-colors"
            :class="card.dark
              ? `rounded-xl shadow-sm ${card.cardBg} hover:bg-slate-700`
              : 'glass-card card-hover'"
            :style="{ animationDelay: (index * 0.08 + 0.1) + 's' }"
          >
            <div class="flex items-center gap-2">
              <div
                class="w-6 h-6 rounded-full flex items-center justify-center shrink-0"
                :class="[card.iconBg, card.iconColor]"
              >
                <span class="w-3 h-3 flex items-center justify-center" v-html="card.icon" />
              </div>
              <span class="text-xs font-medium" :class="card.dark ? card.labelColor : 'text-stone-400'">{{ card.label }}</span>
            </div>
            <span class="text-lg font-bold tabular-nums" :class="card.numColor">
              {{ getAnimatedValue(index) }}
            </span>
          </div>
        </div>

        <!-- 2 个运营统计卡片 -->
        <div class="grid gap-2 grid-cols-2">
          <div
            v-for="(card, index) in visitorCards"
            :key="card.key"
            class="stagger-enter glass-card card-hover h-[44px] px-2.5 flex items-center justify-between transition-colors"
            :style="{ animationDelay: (index * 0.08 + 0.6) + 's' }"
          >
            <div class="flex items-center gap-2">
              <div
                class="w-6 h-6 rounded-full flex items-center justify-center shrink-0"
                :class="[card.iconBg, card.iconColor]"
              >
                <span class="w-3 h-3 flex items-center justify-center" v-html="card.icon" />
              </div>
              <span class="text-xs font-medium text-stone-400">{{ card.label }}</span>
            </div>
            <span class="text-lg font-bold tabular-nums" :class="card.numColor">
              {{ getVisitorDisplayValue(card.key, index) }}
            </span>
          </div>
        </div>
      </div>

      <!-- 日历 -->
      <div class="w-[170px] shrink-0">
        <GlassCalendar
          v-model="currentDate"
          :available-dates="availableDates"
          @update:model-value="onDateChange"
        />
      </div>
    </div>

    <!-- 静默期专用空状态 (Embargo Empty State) -->
    <div
      v-if="!loading && isEmbargoed"
      class="stagger-enter flex flex-col items-center justify-center flex-1 min-h-0 py-20 text-center"
      style="animation-delay: 0.4s"
    >
      <div class="relative mb-6">
        <!-- 外层光晕 -->
        <div class="absolute inset-0 w-24 h-24 rounded-full bg-gradient-to-br from-amber-100 to-orange-50 blur-xl opacity-60" />
        <!-- 图标容器 -->
        <div class="relative w-24 h-24 rounded-2xl bg-gradient-to-br from-amber-50 to-orange-50 border border-amber-200/60 flex items-center justify-center shadow-sm">
          <svg class="w-12 h-12 text-amber-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
            <rect x="3" y="4" width="18" height="18" rx="2" ry="2"/>
            <line x1="16" y1="2" x2="16" y2="6"/>
            <line x1="8" y1="2" x2="8" y2="6"/>
            <line x1="3" y1="10" x2="21" y2="10"/>
            <circle cx="12" cy="16" r="1.5" fill="currentColor" stroke="none"/>
            <line x1="12" y1="12.5" x2="12" y2="14"/>
          </svg>
        </div>
      </div>
      <h3 class="text-xl font-semibold text-stone-700 font-serif tracking-tight">昨日榜单数据整理中</h3>
      <p class="mt-2 text-sm text-stone-400 leading-relaxed max-w-xs">
        最终排位将于今日 <span class="font-semibold text-amber-600">15:00</span>
        <span class="text-stone-300">(UTC+8)</span> 准时发布，敬请期待
      </p>
      <div class="mt-5 flex items-center gap-1.5 text-xs text-stone-300">
        <span class="inline-block w-1.5 h-1.5 rounded-full bg-amber-300 animate-pulse" />
        数据归档进行中…
      </div>
    </div>

    <!-- 全局空状态（非静默期） -->
    <div
      v-else-if="!loading && !hasData && !tabLoading && !isEmbargoed"
      class="stagger-enter flex flex-col items-center justify-center flex-1 min-h-0 py-24 text-center"
      style="animation-delay: 0.5s"
    >
      <div class="w-16 h-16 mb-4 rounded-full flex items-center justify-center bg-stone-100">
        <svg class="w-8 h-8 text-stone-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
          <rect x="3" y="4" width="18" height="18" rx="2" ry="2"/>
          <line x1="16" y1="2" x2="16" y2="6"/>
          <line x1="8" y1="2" x2="8" y2="6"/>
          <line x1="3" y1="10" x2="21" y2="10"/>
          <line x1="9" y1="16" x2="15" y2="16"/>
        </svg>
      </div>
      <h3 class="text-lg font-medium text-stone-500 font-serif">该日期暂无数据</h3>
      <p class="mt-1 text-sm text-stone-400">请尝试在日历中选择其他日期</p>
    </div>

    <!-- 榜单面板（静默期时隐藏） -->
    <div v-if="!loading && hasData && !isEmbargoed" class="stagger-enter glass-card flex-1 min-h-0 flex flex-col overflow-hidden" style="animation-delay: 0.6s">

      <!-- 面板头部：Tab + 周期 -->
      <div class="flex flex-wrap items-center justify-between gap-2 px-4 py-2.5"
        style="border-bottom: 1px solid rgba(168,162,158,0.15)"
      >
        <div class="flex flex-wrap gap-1">
          <button
            v-for="tab in TABS"
            :key="tab.key"
            class="flex items-center gap-1 rounded-full px-3 py-1 text-xs font-medium transition-all duration-200"
            :class="activeTab === tab.key ? 'tab-active' : 'tab-inactive'"
            @click="activeTab = tab.key"
          >
            <component :is="tab.icon" class="h-3.5 w-3.5" />
            {{ tab.label }}
          </button>
        </div>

        <div class="flex items-center gap-1">
          <button
            v-for="period in PERIODS"
            :key="period.key"
            class="rounded-full px-3 py-1 text-xs font-medium transition-all duration-200"
            :class="[
              isPeriodDisabled(period.key)
                ? 'cursor-not-allowed opacity-30 text-stone-400'
                : activePeriod === period.key
                  ? 'bg-stone-700 text-white font-semibold'
                  : 'text-stone-400 hover:bg-stone-100 hover:text-stone-600'
            ]"
            :disabled="isPeriodDisabled(period.key)"
            @click="!isPeriodDisabled(period.key) && (activePeriod = period.key)"
          >
            {{ period.label }}
          </button>
          <span v-if="DAILY_ONLY_TABS.has(activeTab)" class="ml-1 text-2xs text-stone-400">
            仅日榜
          </span>
        </div>
      </div>

      <!-- 定榜状态横幅 (Editorial Status Banner) -->
      <div
        v-if="!isFinalized && !isEmbargoed && !tabLoading"
        class="flex items-center gap-2 px-4 py-1.5 text-xs bg-amber-50/50"
        style="border-bottom: 1px solid rgba(217,119,6,0.1)"
      >
        <Zap class="h-3.5 w-3.5 animate-pulse text-amber-500" />
        <span class="text-stone-600">实时动态初榜 · 正在采集中</span>
      </div>
      <div
        v-else-if="isFinalized && !tabLoading"
        class="flex items-center gap-2 px-4 py-1.5 text-xs bg-emerald-50/30"
        style="border-bottom: 1px solid rgba(16,185,129,0.08)"
      >
        <CheckCircle2 class="h-3.5 w-3.5 text-emerald-500" />
        <span class="text-stone-400">数据已定榜 · 历史排位已永久归档</span>
      </div>

      <!-- 列表内容 -->
      <div class="flex-1 overflow-y-auto">
        <div v-if="tabLoading" class="flex items-center justify-center py-8">
          <span class="inline-block h-5 w-5 rounded-full border-2 border-stone-200 border-t-stone-500 animate-spin" />
        </div>

        <div v-else-if="!tabList.length" class="flex flex-col items-center justify-center py-12 text-stone-400">
          <div class="w-12 h-12 mb-3 rounded-full bg-stone-100 flex items-center justify-center">
            <svg class="h-6 w-6 text-stone-300" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
              <circle cx="12" cy="12" r="10"/>
              <polyline points="12 6 12 12 16 14"/>
            </svg>
          </div>
          <p v-if="!isViewingHistory" class="text-sm font-medium text-stone-500">实时数据采集中，请稍候</p>
          <p v-if="!isViewingHistory" class="mt-1 text-2xs text-stone-400">当前周期数据将在爬虫完成后自动上榜</p>
          <p v-else class="text-sm font-medium text-stone-500">该日期此周期暂无榜单数据</p>
          <p v-if="isViewingHistory" class="mt-1 text-2xs text-stone-400">可能是当天未采集该周期，或数据尚未归档</p>
        </div>

        <!-- 列表（暖色交替背景） -->
        <ol v-else>
          <li
            v-for="(doc, idx) in tabList"
            :key="idx"
            class="group transition-colors duration-150"
            :class="idx % 2 === 0 ? '' : 'bg-stone-50/50'"
            style="border: none"
          >
            <a
              :href="doc.url || undefined"
              :target="doc.url ? '_blank' : undefined"
              :rel="doc.url ? 'noopener noreferrer' : undefined"
              class="flex items-start gap-2.5 px-4 py-2.5"
              :class="doc.url ? 'hover:bg-stone-50 cursor-pointer' : 'pointer-events-none'"
            >
              <!-- 序号 -->
              <span
                class="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-2xs font-bold"
                :class="idx < 3 ? 'bg-stone-700 text-white' : 'bg-stone-100 text-stone-400'"
              >
                {{ idx + 1 }}
              </span>

              <!-- 内容 -->
              <div class="min-w-0 flex-1">
                <div class="flex items-start gap-2">
                  <p
                    class="flex-1 text-sm font-medium text-stone-700 leading-tight group-hover:text-stone-900 line-clamp-1"
                    :class="doc.url ? 'group-hover:underline underline-offset-2' : ''"
                  >
                    {{ doc.title || '(无标题)' }}
                  </p>

                  <div class="flex shrink-0 items-center gap-1.5 ml-2">
                    <span
                      v-if="doc.ai_score !== undefined && doc.ai_score !== null"
                      class="badge bg-white text-stone-600 border border-stone-200"
                      :title="doc.ai_reason || 'AI 评分'"
                    >
                      {{ aiScoreDisplay(doc.ai_score) }}
                    </span>
                    <span class="badge border" :class="getSourceConfig(doc.source).badge">
                      <span class="status-dot shrink-0" :class="getSourceConfig(doc.source).dot" />
                      {{ getSourceConfig(doc.source).label }}
                    </span>
                  </div>
                </div>

                <div class="mt-0.5 flex flex-wrap items-center gap-1.5">
                  <span class="flex items-center gap-0.5 text-2xs text-stone-500 font-medium">
                    <component :is="scoreDisplay(doc).icon" class="h-3 w-3 shrink-0" />
                    {{ scoreDisplay(doc).text }}
                  </span>

                  <span v-if="doc.language" class="badge bg-white text-stone-500 border border-stone-200">
                    {{ doc.language }}
                  </span>

                  <!-- 日期已隐藏：榜单项不再显示日期 -->

                  <span
                    v-for="tag in getModuleTags(doc)"
                    :key="tag"
                    class="badge bg-white text-stone-500 border border-stone-200"
                  >
                    {{ tag }}
                  </span>
                </div>
              </div>

              <!-- 外链图标（所有来源统一） -->
              <svg
                v-if="doc.url"
                class="mt-1 h-3.5 w-3.5 shrink-0 text-stone-300 opacity-0 group-hover:opacity-100 transition-opacity"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                stroke-width="2"
              >
                <path d="M18 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h6"/>
                <polyline points="15 3 21 3 21 9"/>
                <line x1="10" y1="14" x2="21" y2="3"/>
              </svg>
            </a>
          </li>
        </ol>
      </div>
    </div>
  </div>
</template>
