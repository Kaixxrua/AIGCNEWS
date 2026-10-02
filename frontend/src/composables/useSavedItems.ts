import { computed, shallowRef, type ComputedRef, type ShallowRef } from 'vue'
import { useI18n } from 'vue-i18n'
import { showToast } from '@/composables/useToast'

/** 本机收藏的尺度。 */
export const SAVED_ITEMS = {
  /** 每个列表最多收这么多条。收藏连内容一起存在本机（一条推文约 2 KB），满了先取消几条旧的再收。 */
  limit: 200,
  /** 头一回收藏时说一句收藏只存在本机，说过就记下，不再说。 */
  hintKey: 'saved_items_hint',
}

export interface SavedEntry<T> {
  /** 条目的标识：推文按推文 id，简报条目按哪一期加条目内容。 */
  id: string
  /** 收下的时间（毫秒）。 */
  at: number
  /** 收下时的内容：那一页翻过去了、那一天过去了也照样能看。 */
  data: T
}

/** 收藏一条的结果：收下了、取消了、满了没收下。 */
export type SaveOutcome = 'saved' | 'removed' | 'full'

export interface SavedItems<T> {
  /** 收下的条目，最近收的在前。 */
  entries: Readonly<ShallowRef<readonly SavedEntry<T>[]>>
  count: ComputedRef<number>
  has: (id: string) => boolean
  /** 收下或取消一条，data 是收下时连带存下的内容。满了、头一回收、本机存不进去时各说一句。 */
  toggle: (id: string, data: T) => SaveOutcome
}

const storageKey = (list: string) => `saved_items_${list}`

interface Store {
  entries: ShallowRef<readonly SavedEntry<unknown>[]>
  ids: ComputedRef<ReadonlySet<string>>
  /** 本机存不进去（无痕窗口、存满了）：收藏只在这次打开期间有效，也不再跟着别的标签页换。 */
  volatile: boolean
}

// 同一列表在一页里各处（推文墙与详情、简报的条目与页头的计数）共用一份。
const stores = new Map<string, Store>()

/** 本机存着的收藏；存储用不了、内容坏了都当没收过。accept 把关每条存下的内容。 */
function readStored(list: string, accept: (data: unknown) => boolean): SavedEntry<unknown>[] {
  try {
    const parsed: unknown = JSON.parse(localStorage.getItem(storageKey(list)) ?? '[]')
    if (!Array.isArray(parsed)) return []
    const seen = new Set<string>()
    const entries: SavedEntry<unknown>[] = []
    for (const entry of parsed) {
      if (!entry || typeof entry !== 'object') continue
      const { id, at, data } = entry as Partial<SavedEntry<unknown>>
      if (typeof id !== 'string' || !id || seen.has(id) || typeof at !== 'number' || !accept(data)) continue
      seen.add(id)
      entries.push({ id, at, data })
    }
    return entries.slice(0, SAVED_ITEMS.limit)
  } catch {
    return []
  }
}

function writeStored(list: string, entries: readonly SavedEntry<unknown>[]): boolean {
  try {
    localStorage.setItem(storageKey(list), JSON.stringify(entries))
    return true
  } catch {
    return false
  }
}

function storeOf(list: string, accept: (data: unknown) => boolean): Store {
  const existing = stores.get(list)
  if (existing) return existing
  const entries = shallowRef<readonly SavedEntry<unknown>[]>(readStored(list, accept))
  const store: Store = { entries, ids: computed(() => new Set(entries.value.map((entry) => entry.id))), volatile: false }
  stores.set(list, store)
  // 别的标签页收了、取消了：跟着换。
  window.addEventListener('storage', (event) => {
    if (store.volatile || (event.key !== null && event.key !== storageKey(list))) return
    entries.value = readStored(list, accept)
  })
  return store
}

/** 测试用：丢掉各列表共用的那一份，下次从本机存储重读。 */
export function forgetSavedItems() {
  stores.clear()
}

// 收下的是一份脱开页面的快照：响应式代理、后来对原条目的改动都不跟进来。
const snapshot = <T>(data: T): T => JSON.parse(JSON.stringify(data)) as T

/**
 * 本机收藏：推文、简报条目点书签或按 s 收下，连内容一起存在本机浏览器（localStorage，按列表分开），不需要登录，
 * 换一台设备、换个浏览器就看不到。多开的标签页之间跟着同步。
 */
export function useSavedItems<T>(options: { list: string; accept: (data: unknown) => data is T }): SavedItems<T> {
  const { t } = useI18n()
  const { list } = options
  const store = storeOf(list, options.accept)
  const entries = store.entries as ShallowRef<readonly SavedEntry<T>[]>
  const has = (id: string) => store.ids.value.has(id)

  const commit = (next: readonly SavedEntry<unknown>[]) => {
    store.entries.value = next
    if (writeStored(list, next) || store.volatile) return
    store.volatile = true
    showToast(t('saved.volatile'))
  }
  const hintOnce = () => {
    try {
      if (localStorage.getItem(SAVED_ITEMS.hintKey)) return
      localStorage.setItem(SAVED_ITEMS.hintKey, '1')
    } catch {
      return
    }
    showToast(t('saved.hint'))
  }
  const toggle = (id: string, data: T): SaveOutcome => {
    const current = store.entries.value
    if (has(id)) {
      commit(current.filter((entry) => entry.id !== id))
      return 'removed'
    }
    if (current.length >= SAVED_ITEMS.limit) {
      showToast(t('saved.full', { limit: SAVED_ITEMS.limit }))
      return 'full'
    }
    commit([{ id, at: Date.now(), data: snapshot(data) }, ...current])
    if (!store.volatile) hintOnce()
    return 'saved'
  }

  return { entries, count: computed(() => entries.value.length), has, toggle }
}
