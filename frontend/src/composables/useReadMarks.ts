import { onBeforeUnmount, ref, watch, type Directive, type Ref } from 'vue'
import { useEventListener } from '@vueuse/core'

/** 已读记录的尺度。 */
export const READ_MARKS = {
  /** 条目露出至少一半（比屏幕还高的条目占满半屏）并停够这么久（ms）才算看过，滚动时一闪而过的不算。 */
  visible: 0.5,
  dwellMs: 1000,
  /** 每个列表最多记这么多条，多了丢掉最早看过的。 */
  limit: 3000,
  /** 记录留这么多天。 */
  keepDays: 45,
  /** 攒一会儿（ms）再写进本机存储。 */
  flushMs: 800,
}

const MINUTE_MS = 60_000
const storageKey = (list: string) => `read_marks_${list}`
const nowMinutes = () => Math.floor(Date.now() / MINUTE_MS)

/** 本机记下的条目：标识 → 第一次看到的时间（分钟）。存储用不了、内容坏了都当没看过。 */
function readStored(list: string): Map<string, number> {
  const marks = new Map<string, number>()
  try {
    const parsed: unknown = JSON.parse(localStorage.getItem(storageKey(list)) ?? 'null')
    if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
      const oldest = nowMinutes() - READ_MARKS.keepDays * 24 * 60
      for (const [id, at] of Object.entries(parsed)) {
        if (typeof at === 'number' && at >= oldest) marks.set(id, at)
      }
    }
  } catch {
    // 当没看过
  }
  return marks
}

function writeStored(list: string, marks: Map<string, number>) {
  const kept = [...marks].sort((a, b) => b[1] - a[1]).slice(0, READ_MARKS.limit)
  try {
    localStorage.setItem(storageKey(list), JSON.stringify(Object.fromEntries(kept)))
  } catch {
    // 存不了就不存
  }
}

export interface ReadMarks {
  /** 看过的条目：这次进来之前就看过的，加上这次点开过的。 */
  isRead: (id: string) => boolean
  /** 这次进来之前就看过（「上次看到这里」按它画线，这次看的不挪线）。 */
  seenBefore: (id: string) => boolean
  /** 记为看过，下次进来才变淡（比如就地展开读完的条目）。 */
  markSeen: (id: string) => void
  /** 点开了：记为看过并立刻变淡，像访问过的链接。 */
  markOpened: (id: string) => void
  /** 重新开始一次「这次」：换了一批、刷新后调用，这之前看过的都算上回看过的。 */
  snapshot: () => void
  /** v-read-mark="标识"：条目露出来停够时间就记为看过。 */
  directive: Directive<HTMLElement, string | null | undefined>
}

/**
 * 已读淡化：记下列表里看过的条目，下次进来时变淡，列表据此在新旧之间画「上次看到这里」。
 * 记录只存在本机浏览器（localStorage，按列表分开），不需要登录。enabled 关着时不记也不淡（手机和平板不动）。
 */
export function useReadMarks(options: { list: string; enabled: Readonly<Ref<boolean>>; margin?: string }): ReadMarks {
  const { list, enabled } = options
  const marks = readStored(list)
  const before = ref<ReadonlySet<string>>(new Set(marks.keys()))
  const opened = ref<ReadonlySet<string>>(new Set())
  let pending = false
  let flushTimer: ReturnType<typeof setTimeout> | undefined

  const absorbStored = () => {
    for (const [id, at] of readStored(list)) {
      const mine = marks.get(id)
      if (mine === undefined || at < mine) marks.set(id, at)
    }
  }
  // 别的标签页可能也记了：合上存储里的再写回去。
  const flush = () => {
    clearTimeout(flushTimer)
    flushTimer = undefined
    if (!pending) return
    pending = false
    absorbStored()
    writeStored(list, marks)
  }
  const markSeen = (id: string) => {
    if (!enabled.value || !id || marks.has(id)) return
    marks.set(id, nowMinutes())
    pending = true
    flushTimer ??= setTimeout(flush, READ_MARKS.flushMs)
  }
  const markOpened = (id: string) => {
    if (!enabled.value || !id) return
    markSeen(id)
    if (!opened.value.has(id)) opened.value = new Set(opened.value).add(id)
  }
  const snapshot = () => {
    flush()
    absorbStored()
    before.value = new Set(marks.keys())
    opened.value = new Set()
  }
  const seenBefore = (id: string) => enabled.value && before.value.has(id)
  const isRead = (id: string) => enabled.value && (before.value.has(id) || opened.value.has(id))

  // ── 露出计时：IntersectionObserver 看各条露出多少，够一半就起表，停够 dwellMs 记为看过 ──
  const ids = new Map<HTMLElement, string>()
  const inView = new Set<HTMLElement>()
  const timers = new Map<HTMLElement, ReturnType<typeof setTimeout>>()
  let observer: IntersectionObserver | null = null

  const stopTimer = (el: HTMLElement) => {
    clearTimeout(timers.get(el))
    timers.delete(el)
  }
  const stopAll = () => [...timers.keys()].forEach(stopTimer)
  const startTimer = (el: HTMLElement) => {
    const id = ids.get(el)
    if (timers.has(el) || !id || marks.has(id) || document.visibilityState === 'hidden') return
    timers.set(el, setTimeout(() => {
      timers.delete(el)
      const current = ids.get(el)
      if (current && inView.has(el)) markSeen(current)
    }, READ_MARKS.dwellMs))
  }
  const qualifies = (entry: IntersectionObserverEntry) => entry.isIntersecting && (
    entry.intersectionRatio >= READ_MARKS.visible
    || (!!entry.rootBounds && entry.intersectionRect.height >= entry.rootBounds.height * READ_MARKS.visible))
  const onIntersect = (entries: IntersectionObserverEntry[]) => {
    for (const entry of entries) {
      const el = entry.target as HTMLElement
      if (qualifies(entry)) {
        inView.add(el)
        startTimer(el)
      } else {
        inView.delete(el)
        stopTimer(el)
      }
    }
  }
  // 根是视口：各页自己的滚动容器会裁掉滚出去的部分；上下让开刊头和 dock。
  const track = (el: HTMLElement) => {
    if (!enabled.value || typeof IntersectionObserver === 'undefined') return
    observer ??= new IntersectionObserver(onIntersect, {
      rootMargin: options.margin ?? '-56px 0px -64px 0px',
      threshold: [0, 0.25, 0.5, 0.75, 1],
    })
    observer.observe(el)
  }
  const untrack = (el: HTMLElement) => {
    observer?.unobserve(el)
    inView.delete(el)
    stopTimer(el)
  }

  const directive: Directive<HTMLElement, string | null | undefined> = {
    mounted(el, { value }) {
      if (!value) return
      ids.set(el, value)
      track(el)
    },
    // 同一个元素换成了别的条目（按位置复用的列表）：重新观察，刚好停在视野里的也会重新起表。
    updated(el, { value, oldValue }) {
      if (value === oldValue) return
      untrack(el)
      ids.delete(el)
      if (!value) return
      ids.set(el, value)
      track(el)
    },
    unmounted(el) {
      untrack(el)
      ids.delete(el)
    },
  }

  watch(enabled, (on) => {
    if (on) {
      ids.forEach((_, el) => track(el))
    } else {
      observer?.disconnect()
      inView.clear()
      stopAll()
    }
  })
  // 切到别的标签页时停表，回来接着计；离开前把攒着的写进去。
  useEventListener(document, 'visibilitychange', () => {
    if (document.visibilityState === 'hidden') {
      stopAll()
      flush()
    } else {
      inView.forEach(startTimer)
    }
  })
  useEventListener(window, 'pagehide', flush)
  onBeforeUnmount(() => {
    observer?.disconnect()
    stopAll()
    flush()
  })

  return { isRead, seenBefore, markSeen, markOpened, snapshot, directive }
}
