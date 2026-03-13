<script setup lang="ts">
import { nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import MarkdownIt from 'markdown-it'
import { api } from '../services/api'
import { useEventSource } from '../composables/useEventSource'

const md = new MarkdownIt({ html: false, linkify: true, breaks: true })

const reportContent = ref('')
const isGenerating = ref(false)
const isCached = ref(false)
const errorMsg = ref('')
const reportRef = ref<HTMLElement | null>(null)

const REPORT_TYPES = [
  { key: 'all',         label: '综合简报', icon: '🌐', desc: '全源汇总' },
  { key: 'arxiv',       label: '学术报告', icon: '📄', desc: 'HF Papers' },
  { key: 'github',      label: '工程报告', icon: '💻', desc: 'GitHub Hot' },
  { key: 'news',        label: '行业报告', icon: '📰', desc: 'RSS 新闻' },
  { key: 'producthunt', label: '产品报告', icon: '🚀', desc: 'Product Hunt' },
  { key: 'hackernews',  label: '社区报告', icon: '🟠', desc: 'Hacker News' },
] as const

const PERIOD_TYPES = [
  { key: 'daily',   label: '日报' },
  { key: 'weekly',  label: '周报' },
  { key: 'monthly', label: '月报' },
] as const

const DAILY_ONLY_TYPES = new Set(['all', 'news', 'producthunt', 'hackernews'])

type ReportKey = (typeof REPORT_TYPES)[number]['key']
type PeriodKey = (typeof PERIOD_TYPES)[number]['key']

const selectedType   = ref<ReportKey>('all')
const selectedPeriod = ref<PeriodKey>('daily')
const selectedDate   = ref<string>(new Date().toISOString().slice(0, 10))

const isPeriodDisabled = (periodKey: PeriodKey): boolean =>
  periodKey !== 'daily' && DAILY_ONLY_TYPES.has(selectedType.value)

const autoScroll = ref(true)
const onWheelHandler = (e: WheelEvent) => { if (e.deltaY < 0) autoScroll.value = false }
let lastTouchY = 0
const onTouchStart = (e: TouchEvent) => { lastTouchY = e.touches[0]?.clientY ?? 0 }
const onTouchMoveHandler = (e: TouchEvent) => {
  const currentY = e.touches[0]?.clientY ?? 0
  if (currentY > lastTouchY) autoScroll.value = false
  lastTouchY = currentY
}

const scrollToBottom = async () => {
  if (!autoScroll.value) return
  await nextTick()
  const el = reportRef.value
  if (!el) return
  el.scrollTop = el.scrollHeight
}

onMounted(() => {
  const el = reportRef.value
  if (el) {
    el.addEventListener('wheel', onWheelHandler, { passive: true })
    el.addEventListener('touchstart', onTouchStart, { passive: true })
    el.addEventListener('touchmove', onTouchMoveHandler, { passive: true })
  }
})

onUnmounted(() => {
  const el = reportRef.value
  if (el) {
    el.removeEventListener('wheel', onWheelHandler)
    el.removeEventListener('touchstart', onTouchStart)
    el.removeEventListener('touchmove', onTouchMoveHandler)
  }
})

const generate = async () => {
  if (isGenerating.value) return
  isGenerating.value = true
  reportContent.value = ''
  errorMsg.value = ''
  autoScroll.value = true

  const { connect } = useEventSource()
  await connect({
    url: 'http://localhost:8001/api/report/daily/stream',
    body: {
      source: selectedType.value,
      date: selectedDate.value,
      period: selectedPeriod.value,
      force_regenerate: true,
    },
    onMessage: async (payload: unknown) => {
      const event = payload as { type: string; data?: unknown }
      if (event.type === 'content' || event.type === 'chunk') {
        // 防御：data 可能是对象/数组（如 Anthropic Extended Thinking 的块列表）
        let text = ''
        const d = event.data
        if (typeof d === 'string') {
          text = d
        } else if (Array.isArray(d)) {
          text = d
            .map((b: unknown) =>
              typeof b === 'string' ? b : (b as Record<string, unknown>)?.text ?? '',
            )
            .join('')
        } else {
          text = d != null ? JSON.stringify(d) : ''
        }
        reportContent.value += text
        await scrollToBottom()
      } else if (event.type === 'error') {
        errorMsg.value = String(event.data ?? 'Unknown error')
      }
    },
    onDone: () => { isGenerating.value = false },
    onError: (err: unknown) => { errorMsg.value = String(err); isGenerating.value = false },
  })
}

const currentTypeInfo = () => REPORT_TYPES.find(t => t.key === selectedType.value)

const loadCachedReport = async () => {
  try {
    const res = await api.get<{ content: string; date: string; id: number }>('/report/latest', {
      params: { source: selectedType.value, period: selectedPeriod.value, date: selectedDate.value },
    })
    if (res.data?.content) { reportContent.value = res.data.content; isCached.value = true; errorMsg.value = ''; return }
    reportContent.value = ''; isCached.value = false
  } catch { reportContent.value = ''; isCached.value = false }
}

onMounted(loadCachedReport)

watch(selectedType, (type) => {
  if (DAILY_ONLY_TYPES.has(type) && selectedPeriod.value !== 'daily') selectedPeriod.value = 'daily'
})

watch([selectedType, selectedPeriod, selectedDate], () => {
  if (isGenerating.value) return
  void loadCachedReport()
})
</script>

<template>
  <div class="flex h-full flex-col gap-4 overflow-hidden p-6">

    <!-- 页头 -->
    <div class="stagger-enter flex items-end justify-between shrink-0">
      <div>
        <h1 class="text-2xl font-bold text-stone-800 tracking-tight font-serif">自动化简报</h1>
        <p class="mt-0.5 text-sm text-stone-400">基于多源数据，由 LLM 自动生成结构化简报</p>
      </div>
      <div v-if="isCached && !isGenerating" class="flex items-center gap-1.5 rounded-full bg-green-50 px-3 py-1.5 border border-green-200">
        <span class="status-dot bg-brand-green" />
        <span class="text-xs font-medium text-green-700">已缓存</span>
      </div>
    </div>

    <!-- 控制面板 -->
    <div class="stagger-enter glass-card shrink-0 p-5 space-y-3" style="animation-delay: 0.1s">
      <div class="flex flex-wrap gap-2">
        <button
          v-for="type in REPORT_TYPES"
          :key="type.key"
          class="flex items-center gap-2 rounded-full px-4 py-2 text-sm font-medium transition-all duration-200"
          :class="selectedType === type.key
            ? 'bg-stone-700 text-white shadow-sm'
            : 'text-stone-500 hover:bg-stone-50 hover:text-stone-700'"
          :style="selectedType !== type.key ? 'background: rgba(255,255,255,0.6); border: 1px solid rgba(168,162,158,0.20)' : ''"
          :disabled="isGenerating"
          @click="selectedType = type.key"
        >
          <span>{{ type.icon }}</span>
          <span>{{ type.label }}</span>
          <span class="text-2xs font-normal hidden sm:inline" :class="selectedType === type.key ? 'text-white/60' : 'text-stone-400'">{{ type.desc }}</span>
        </button>
      </div>

      <div class="flex flex-wrap items-center gap-3 pt-3" style="border-top: 1px solid rgba(168,162,158,0.15)">
        <div class="flex items-center gap-1.5">
          <span class="text-xs text-stone-400 shrink-0">周期：</span>
          <div class="flex gap-1.5">
            <button
              v-for="p in PERIOD_TYPES"
              :key="p.key"
              class="rounded-full px-4 py-1.5 text-xs font-medium transition-all duration-200"
              :class="[
                isPeriodDisabled(p.key) ? 'cursor-not-allowed opacity-30 text-stone-400'
                  : selectedPeriod === p.key ? 'bg-green-50 text-green-700 font-semibold border border-green-200'
                  : 'text-stone-400 hover:bg-stone-50 hover:text-stone-600'
              ]"
              :disabled="isGenerating || isPeriodDisabled(p.key)"
              @click="!isPeriodDisabled(p.key) && (selectedPeriod = p.key)"
            >{{ p.label }}</button>
          </div>
          <span v-if="DAILY_ONLY_TYPES.has(selectedType)" class="text-2xs text-stone-400">📌 仅日报</span>
        </div>

        <div class="flex items-center gap-1.5">
          <span class="text-xs text-stone-400 shrink-0">日期：</span>
          <input v-model="selectedDate" type="date" class="input w-auto py-1.5 text-xs" :disabled="isGenerating" />
        </div>

        <div class="ml-auto flex items-center gap-3">
          <span v-if="isGenerating" class="flex items-center gap-1.5 text-xs" :class="autoScroll ? 'text-green-600' : 'text-stone-400'">
            <span class="status-dot" :class="autoScroll ? 'bg-brand-green animate-[pulseDot_2s_ease-in-out_infinite]' : 'bg-stone-400'" />
            {{ autoScroll ? '跟随底部' : '已解锁' }}
          </span>
          <button class="btn-primary gap-2" :disabled="isGenerating" @click="generate">
            <span v-if="isGenerating" class="h-3.5 w-3.5 rounded-full border-2 border-white/40 border-t-white animate-spin" />
            <svg v-else class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"/></svg>
            {{ isGenerating ? '生成中…' : isCached ? '重新生成' : '生成报告' }}
          </button>
        </div>
      </div>
    </div>

    <!-- 错误 -->
    <div v-if="errorMsg" class="shrink-0 glass-card flex items-center gap-2 px-5 py-3 text-sm text-rose-600">
      <svg class="h-4 w-4 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
      {{ errorMsg }}
    </div>

    <!-- 内容区 -->
    <div ref="reportRef" class="stagger-enter glass-card relative flex-1 min-h-0 overflow-y-auto p-6 scroll-smooth" style="animation-delay: 0.25s">
      <div v-if="!reportContent && !isGenerating" class="flex h-full flex-col items-center justify-center gap-3 text-stone-400">
        <div class="flex h-16 w-16 items-center justify-center rounded-3xl bg-stone-100">
          <svg class="h-8 w-8 opacity-30" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/></svg>
        </div>
        <p class="text-sm font-medium text-stone-500 font-serif">选择类型并点击生成</p>
        <p class="text-xs text-center max-w-sm text-stone-400">支持综合简报 · 学术 · 工程 · 行业 · 产品 · 社区<br/>日报 / 周报（学术/工程）/ 月报（学术/工程）</p>
        <p class="mt-1 text-2xs text-stone-400">正在检查缓存…</p>
      </div>

      <div v-if="isGenerating && !reportContent" class="flex items-center gap-2 text-sm text-stone-500">
        <span class="status-dot bg-stone-500 animate-[pulseDot_2s_ease-in-out_infinite]" />
        正在生成「{{ currentTypeInfo()?.label }}」，请稍候…
      </div>

      <article v-if="reportContent" class="prose-content max-w-none" v-html="md.render(reportContent)" />

      <span v-if="isGenerating && reportContent" class="inline-block h-4 w-0.5 animate-pulse bg-stone-500 align-middle ml-0.5" />

      <button
        v-if="isGenerating && !autoScroll"
        class="sticky bottom-4 ml-auto btn-primary text-xs"
        @click="() => { autoScroll = true; scrollToBottom() }"
      >
        <svg class="h-3 w-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/></svg>
        回到底部
      </button>
    </div>
  </div>
</template>
