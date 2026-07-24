<script setup lang="ts">
/**
 * GlobalSearch.vue
 * 顶部全局搜索框（Ctrl/Cmd+K 唤醒，300ms debounce，空输入时展示今日 Top10）
 */
import { ref, watch, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import {
  GLOBAL_SEARCH_BLUR_DELAY_MS,
  GLOBAL_SEARCH_DEBOUNCE_MS,
  GLOBAL_SEARCH_RESULT_LIMIT,
  getGlobalSearchDestination,
  getSearchSourceLabel,
  getSearchSummaryPreview,
} from '../features/search/globalSearchModel'
import { searchPapers, fetchTop10Today, type PaperItem } from '../services/api'

const router = useRouter()
const inputRef = ref<HTMLInputElement | null>(null)
const query = ref('')
const results = ref<PaperItem[]>([])
const showDropdown = ref(false)
const loading = ref(false)
const focused = ref(false)

// ── Debounce 300ms ─────────────────────────────────────────────────────────
let debounceTimer: ReturnType<typeof setTimeout> | null = null

const triggerSearch = () => {
  if (debounceTimer) clearTimeout(debounceTimer)
  debounceTimer = setTimeout(async () => {
    const q = query.value.trim()
    if (!q) {
      await loadTop10()
    } else {
      loading.value = true
      try {
        results.value = await searchPapers(q, GLOBAL_SEARCH_RESULT_LIMIT)
      } finally {
        loading.value = false
      }
    }
  }, GLOBAL_SEARCH_DEBOUNCE_MS)
}

const loadTop10 = async () => {
  loading.value = true
  try {
    results.value = await fetchTop10Today()
  } finally {
    loading.value = false
  }
}

watch(query, triggerSearch)

// ── 聚焦时若空输入自动加载 Top10 ──────────────────────────────────────────
const onFocus = async () => {
  focused.value = true
  showDropdown.value = true
  if (!query.value.trim() && results.value.length === 0) {
    await loadTop10()
  }
}

const onBlur = () => {
  // 延迟关闭，允许用户点击结果项
  setTimeout(() => {
    focused.value = false
    showDropdown.value = false
  }, GLOBAL_SEARCH_BLUR_DELAY_MS)
}

// ── 点击搜索结果 ───────────────────────────────────────────────────────────
const onSelectItem = (item: PaperItem) => {
  showDropdown.value = false
  query.value = ''
  results.value = []

  const destination = getGlobalSearchDestination(item)
  if (destination.kind === 'route') {
    // 论文 → 沉浸阅读页
    router.push(destination.location)
  } else if (destination.kind === 'external') {
    // 其他来源 → 原始链接
    window.open(destination.url, '_blank', 'noopener,noreferrer')
  }
}

// ── Ctrl/Cmd+K 聚焦唤醒 ───────────────────────────────────────────────────
const onGlobalKeydown = (e: KeyboardEvent) => {
  if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
    e.preventDefault()
    inputRef.value?.focus()
    showDropdown.value = true
    if (!query.value.trim()) loadTop10()
  }
  if (e.key === 'Escape') {
    showDropdown.value = false
    inputRef.value?.blur()
  }
}

onMounted(() => window.addEventListener('keydown', onGlobalKeydown))
onUnmounted(() => window.removeEventListener('keydown', onGlobalKeydown))
</script>

<template>
  <div class="relative w-full max-w-sm mx-auto" style="z-index: 200">
    <!-- 搜索输入框 -->
    <div
      class="flex items-center gap-2 rounded-2xl px-3 py-1.5 text-sm transition-all"
      :class="focused
        ? 'bg-white border border-stone-300 shadow-md'
        : 'bg-stone-100/80 border border-transparent'"
    >
      <!-- 搜索图标 -->
      <svg class="h-3.5 w-3.5 shrink-0 text-stone-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-4.35-4.35M17 11A6 6 0 115 11a6 6 0 0112 0z"/>
      </svg>

      <input
        ref="inputRef"
        v-model="query"
        type="text"
        placeholder="搜索论文、项目…"
        class="flex-1 bg-transparent text-xs text-stone-700 outline-none placeholder:text-stone-400 min-w-0"
        @focus="onFocus"
        @blur="onBlur"
      />

      <!-- 加载动画 -->
      <svg v-if="loading" class="h-3 w-3 animate-spin text-stone-400 shrink-0" fill="none" viewBox="0 0 24 24">
        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="3"/>
        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z"/>
      </svg>

      <!-- 快捷键提示（未聚焦时） -->
      <span v-if="!focused" class="shrink-0 text-2xs text-stone-400 font-mono select-none">⌘K</span>
    </div>

    <!-- 下拉结果列表 -->
    <Transition name="search-drop">
      <div
        v-if="showDropdown && results.length > 0"
        class="absolute left-0 right-0 top-full mt-1.5 max-h-72 overflow-y-auto rounded-2xl py-1 shadow-xl"
        style="background: rgba(255,255,255,0.97); border: 1px solid rgba(168,162,158,0.20); backdrop-filter: blur(16px);"
      >
        <!-- 列表头部 -->
        <p class="px-3 py-1.5 text-2xs font-semibold uppercase tracking-widest text-stone-400">
          {{ query.trim() ? `搜索结果 · ${results.length} 条` : '今日热门推荐' }}
        </p>

        <button
          v-for="item in results"
          :key="item.id"
          class="search-result flex w-full items-start gap-2.5 px-3 py-2 text-left text-xs transition group"
          @mousedown.prevent="onSelectItem(item)"
        >
          <!-- 来源标签 -->
          <span
            class="mt-0.5 shrink-0 rounded-md border px-1.5 py-0.5 text-2xs font-medium text-stone-500 border-stone-200 bg-white"
          >{{ getSearchSourceLabel(item.source) }}</span>

          <!-- 标题 + 摘要 -->
          <span class="min-w-0 flex-1">
            <span class="block truncate font-medium text-stone-700 group-hover:text-stone-900">{{ item.title }}</span>
            <span v-if="item.summary" class="block mt-0.5 truncate text-stone-400">{{ getSearchSummaryPreview(item.summary) }}</span>
          </span>

          <!-- 论文可进入阅读的箭头提示 -->
          <svg v-if="item.source === 'arxiv'" class="mt-0.5 h-3.5 w-3.5 shrink-0 text-stone-300 group-hover:text-stone-500 transition" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"/>
          </svg>
        </button>
      </div>
    </Transition>

    <!-- 搜索无结果提示 -->
    <Transition name="search-drop">
      <div
        v-if="showDropdown && !loading && results.length === 0 && query.trim()"
        class="absolute left-0 right-0 top-full mt-1.5 rounded-2xl px-4 py-3 text-xs text-stone-400 shadow-lg"
        style="background: rgba(255,255,255,0.97); border: 1px solid rgba(168,162,158,0.20);"
      >
        无匹配结果
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.search-result:hover,
.search-result:focus-visible {
  color: var(--ink);
  background: var(--acid-soft);
}

.search-drop-enter-active,
.search-drop-leave-active {
  transition: opacity 0.12s ease, transform 0.12s ease;
}
.search-drop-enter-from,
.search-drop-leave-to {
  opacity: 0;
  transform: translateY(-4px) scale(0.98);
}
</style>
