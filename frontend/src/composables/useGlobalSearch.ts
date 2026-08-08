import { onMounted, onUnmounted, ref, watch, type Ref } from 'vue'
import type { RouteLocationRaw } from 'vue-router'
import {
  GLOBAL_SEARCH_BLUR_DELAY_MS,
  GLOBAL_SEARCH_DEBOUNCE_MS,
  GLOBAL_SEARCH_RESULT_LIMIT,
  getGlobalSearchDestination,
} from '@/features/search/globalSearchModel'
import type { PaperItem } from '@/services/papers/paperApi'

interface GlobalSearchInputHandle {
  focus: () => void
  blur: () => void
}

interface GlobalSearchDependencies {
  inputRef: Ref<GlobalSearchInputHandle | null>
  search: (query: string, limit: number, signal?: AbortSignal) => Promise<PaperItem[]>
  fetchTop10: (signal?: AbortSignal) => Promise<PaperItem[]>
  push: (location: RouteLocationRaw) => void | Promise<unknown>
  openExternal: (url: string) => void
}

export const useGlobalSearch = ({
  inputRef,
  search,
  fetchTop10,
  push,
  openExternal,
}: GlobalSearchDependencies) => {
  const query = ref('')
  const results = ref<PaperItem[]>([])
  const showDropdown = ref(false)
  const loading = ref(false)
  const focused = ref(false)
  let debounceTimer: ReturnType<typeof setTimeout> | null = null
  // generation + AbortController 竞态守卫（对齐 useXBoardController）：
  // 只应用最新一次请求的结果，loading 也只由最新请求复位，避免两个请求 finally 互相串扰
  const isActive = ref(true)
  let generation = 0
  let abortController: AbortController | null = null

  const runRequest = async (execute: (signal: AbortSignal) => Promise<PaperItem[]>) => {
    const request = ++generation
    abortController?.abort()
    const controller = new AbortController()
    abortController = controller
    loading.value = true
    try {
      const data = await execute(controller.signal)
      if (isActive.value && request === generation) results.value = data
    } catch (error) {
      if (!controller.signal.aborted && isActive.value && request === generation) {
        console.error('Global search request failed:', error)
        results.value = []
      }
    } finally {
      if (isActive.value && request === generation) loading.value = false
    }
  }

  const loadTop10 = () => runRequest((signal) => fetchTop10(signal))

  const triggerSearch = () => {
    if (debounceTimer) clearTimeout(debounceTimer)
    debounceTimer = setTimeout(() => {
      const q = query.value.trim()
      if (!q) {
        void loadTop10()
      } else {
        void runRequest((signal) => search(q, GLOBAL_SEARCH_RESULT_LIMIT, signal))
      }
    }, GLOBAL_SEARCH_DEBOUNCE_MS)
  }

  watch(query, triggerSearch)

  const onFocus = async () => {
    focused.value = true
    showDropdown.value = true
    if (!query.value.trim() && results.value.length === 0) {
      await loadTop10()
    }
  }

  const onBlur = () => {
    setTimeout(() => {
      focused.value = false
      showDropdown.value = false
    }, GLOBAL_SEARCH_BLUR_DELAY_MS)
  }

  const onSelectItem = (item: PaperItem) => {
    showDropdown.value = false
    query.value = ''
    results.value = []

    const destination = getGlobalSearchDestination(item)
    if (destination.kind === 'route') {
      void push(destination.location)
    } else if (destination.kind === 'external') {
      openExternal(destination.url)
    }
  }

  const onGlobalKeydown = (event: KeyboardEvent) => {
    if ((event.ctrlKey || event.metaKey) && event.key === 'k') {
      event.preventDefault()
      inputRef.value?.focus()
      showDropdown.value = true
      if (!query.value.trim()) void loadTop10()
    }
    if (event.key === 'Escape') {
      showDropdown.value = false
      inputRef.value?.blur()
    }
  }

  onMounted(() => window.addEventListener('keydown', onGlobalKeydown))
  onUnmounted(() => {
    window.removeEventListener('keydown', onGlobalKeydown)
    isActive.value = false
    generation += 1
    abortController?.abort()
    abortController = null
    if (debounceTimer) {
      clearTimeout(debounceTimer)
      debounceTimer = null
    }
    loading.value = false
  })

  return {
    query,
    results,
    showDropdown,
    loading,
    focused,
    onFocus,
    onBlur,
    onSelectItem,
  }
}
