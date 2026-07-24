import { onMounted, onUnmounted, ref, watch, type Ref } from 'vue'
import type { RouteLocationRaw } from 'vue-router'
import {
  GLOBAL_SEARCH_BLUR_DELAY_MS,
  GLOBAL_SEARCH_DEBOUNCE_MS,
  GLOBAL_SEARCH_RESULT_LIMIT,
  getGlobalSearchDestination,
} from '../features/search/globalSearchModel'
import type { PaperItem } from '../services/api'

interface GlobalSearchInputHandle {
  focus: () => void
  blur: () => void
}

interface GlobalSearchDependencies {
  inputRef: Ref<GlobalSearchInputHandle | null>
  search: (query: string, limit: number) => Promise<PaperItem[]>
  fetchTop10: () => Promise<PaperItem[]>
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

  const loadTop10 = async () => {
    loading.value = true
    try {
      results.value = await fetchTop10()
    } finally {
      loading.value = false
    }
  }

  const triggerSearch = () => {
    if (debounceTimer) clearTimeout(debounceTimer)
    debounceTimer = setTimeout(async () => {
      const q = query.value.trim()
      if (!q) {
        await loadTop10()
      } else {
        loading.value = true
        try {
          results.value = await search(q, GLOBAL_SEARCH_RESULT_LIMIT)
        } finally {
          loading.value = false
        }
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
  onUnmounted(() => window.removeEventListener('keydown', onGlobalKeydown))

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
