import { computed, ref, watch } from 'vue'

interface AccountSubscriptions {
  mode: 'include' | 'exclude'
  handles: string[]
}

const PREFERENCE_KEY = 'aigcnews.x.accountSubscriptions'
const LEGACY_KEY = 'aigcnews.x.unfollowedAccounts'
const DEFAULT_HANDLES = ['openai', 'thsottiaux', 'anthropicai', 'chatgptapp']
const normalize = (handle: string) => handle.trim().replace(/^@+/, '').toLowerCase()
const normalizeHandles = (handles: string[]) => [...new Set(handles.map(normalize).filter(Boolean))]

function readSubscriptions(): AccountSubscriptions {
  try {
    const saved = JSON.parse(localStorage.getItem(PREFERENCE_KEY) || 'null') as Partial<AccountSubscriptions> | null
    if (saved && (saved.mode === 'include' || saved.mode === 'exclude')
      && Array.isArray(saved.handles) && saved.handles.every(handle => typeof handle === 'string')) {
      return { mode: saved.mode, handles: normalizeHandles(saved.handles) }
    }
  } catch { /* Invalid or unavailable storage falls back to the previous preference. */ }
  try {
    const legacy: unknown = JSON.parse(localStorage.getItem(LEGACY_KEY) || 'null')
    // Preserve earlier selections, including an explicit "follow all" ([]).
    if (Array.isArray(legacy)) {
      return { mode: 'exclude', handles: normalizeHandles(legacy.filter((handle): handle is string => typeof handle === 'string')) }
    }
  } catch { /* Fresh visitors use the default subscriptions. */ }
  return { mode: 'include', handles: [...DEFAULT_HANDLES] }
}

export function useXAccountSubscriptions() {
  const preference = ref(readSubscriptions())
  const handles = computed(() => new Set(preference.value.handles))
  const follows = (handle: string) => preference.value.mode === 'include'
    ? handles.value.has(normalize(handle))
    : !handles.value.has(normalize(handle))

  watch(preference, (value) => {
    try { localStorage.setItem(PREFERENCE_KEY, JSON.stringify(value)) } catch { /* Keep the in-memory selection. */ }
  }, { flush: 'sync' })

  return {
    follows,
    toggle(handle: string) {
      const next = new Set(handles.value)
      const normalized = normalize(handle)
      if (!next.delete(normalized)) next.add(normalized)
      preference.value = { ...preference.value, handles: [...next] }
    },
    followAll() { preference.value = { mode: 'exclude', handles: [] } },
    unfollowAll() { preference.value = { mode: 'include', handles: [] } },
  }
}
