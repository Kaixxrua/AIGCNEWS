import { computed, onActivated, onBeforeUnmount, onDeactivated, ref, shallowReactive, watch, type Ref } from 'vue'
import { useEventListener } from '@vueuse/core'
import { viewOf } from '@/composables/useListKeys'
import { PEEK_CURVE_DAYS, peekPlacement, type PeekPlacement } from '@/features/projects/projectPeek'
import {
  fetchProjectPeek,
  fetchProjectTrends,
  type GitHubProjectPeek,
  type GitHubProjectTrendPoint,
  type GitHubProjectTrendsResponse,
} from '@/services/projects/projectApi'

/**
 * 榜单悬停速览：鼠标在一行上停稳半秒，这一行下面（下面放不下就上面）浮出一张卡片，写着 README 开头几段、
 * 默认分支最近一次提交和近 30 天的星标曲线，不用离开列表。
 * - 停稳：指针一直在这一行里、离开始计时的地方不超过几像素。一直在挪就不浮，扫过榜单不会一路弹卡片。
 * - 卡片开着（或刚收起）时换到别的行，稍停一下就换成那一行的。
 * - 指针挪进卡片里卡片留着，可以点里面的链接、在里面滚；离开这一行和卡片后稍等一下就收起。
 * - 按键（Esc 由键盘流先交给它收卡片）、滚动榜单、点别处、切走窗口、翻页或筛选换了一批行，都直接收起。
 * 只认鼠标：触屏、手写笔和按着键拖选文字时不浮。取数交给 useProjectPeekData，宽屏的详情栏也用同一份。
 */
export const PEEK_OPEN_DELAY = 500
export const PEEK_SWITCH_DELAY = 150
export const PEEK_CLOSE_GRACE = 160
/** 卡片收起后这么久之内停到别的行上，照卡片开着时那样稍停就浮 */
export const PEEK_WARM_MS = 800
/** 停稳：离开始计时的地方不超过这么远（px） */
export const PEEK_STILL_RADIUS = 8
const CACHE_MS = 10 * 60_000
/** 没取到的（连读不到 GitHub 的）过一会儿再取；一直没回来的请求过这么久也不再等 */
const RETRY_MS = 30_000
const CACHE_SIZE = 120
/** 与后端行情接口一次最多的仓库数（TRENDS_MAX_REPOS）一致 */
const TRENDS_BATCH = 60
const CARD = '[data-project-peek]'
/** 不收卡片的键：单按修饰键、Tab（焦点走进卡片里）和 Esc（由键盘流交给 close） */
const KEEP_KEYS = new Set(['Shift', 'Control', 'Alt', 'Meta', 'CapsLock', 'Tab', 'Escape'])

export interface PeekTarget {
  /** 行的 data-list-key */
  key: string
  /** 速览查的仓库（owner/repo） */
  repoId: string
}

export type PeekContent =
  | { status: 'loading' }
  | { status: 'ready'; peek: GitHubProjectPeek }
  | { status: 'error' }

export type PeekCurveState =
  | { status: 'loading' }
  | { status: 'ready'; points: GitHubProjectTrendPoint[]; metricDate: string; days: number }
  | { status: 'error' }

export interface ProjectPeekDataOptions {
  /** 这一页各行的 key，按阅读顺序：曲线一次取这一页还没取过的 */
  keys: Ref<readonly string[]>
  /** 行的 key 换成速览查的仓库；网页收藏等没有速览的给 '' */
  repoOf: (key: string) => string
  load?: (repoId: string) => Promise<GitHubProjectPeek>
  loadTrends?: (repoIds: string[]) => Promise<GitHubProjectTrendsResponse>
  now?: () => number
}

interface Cached<T> {
  state: T
  at: number
}

const peekKept = (state: PeekContent) => state.status === 'ready' && state.peek.status === 'ok'
const curveKept = (state: PeekCurveState) => state.status === 'ready'

/**
 * 速览的数据：README 开头几段与最近一次提交（一个仓库取一次）、近 30 天的星标曲线（一次取这一页还没取过的全部仓库，
 * 看着的这个排第一，接着看下一行时不用再等）。悬停速览和宽屏的详情栏共用一份，在哪边看过的换到另一边不用再取。
 * 取到的在前端存十分钟；没取到的、读不到 GitHub 的过半分钟再取，retry 马上再取。
 */
export function useProjectPeekData({
  keys,
  repoOf,
  load = (repoId) => fetchProjectPeek(repoId),
  loadTrends = (repoIds) => fetchProjectTrends(repoIds, { days: PEEK_CURVE_DAYS }),
  now = () => Date.now(),
}: ProjectPeekDataOptions) {
  const peeks = shallowReactive(new Map<string, Cached<PeekContent>>())
  const curves = shallowReactive(new Map<string, Cached<PeekCurveState>>())

  const remember = <T>(cache: Map<string, Cached<T>>, key: string, state: T) => {
    cache.delete(key)
    cache.set(key, { state, at: now() })
    while (cache.size > CACHE_SIZE) cache.delete(cache.keys().next().value as string)
  }
  /** 正在取、取到了还新鲜、没取到但刚试过的，这次都不取 */
  const settled = <T>(entry: Cached<T> | undefined, at: number, kept: (state: T) => boolean) => {
    if (!entry) return false
    return at - entry.at < (kept(entry.state) ? CACHE_MS : RETRY_MS)
  }

  /** 只取 README 和提交（详情栏顺手预取前后两行用） */
  const fetchPeek = (repoId: string) => {
    if (!repoId || settled(peeks.get(repoId), now(), peekKept)) return
    remember(peeks, repoId, { status: 'loading' })
    load(repoId).then(
      (peek) => remember(peeks, repoId, { status: 'ready', peek }),
      () => remember(peeks, repoId, { status: 'error' }),
    )
  }

  /** 曲线一次取这一页还没取过的全部仓库，看着的这个排第一。 */
  const fetchCurves = (repoId: string) => {
    const at = now()
    if (!repoId || settled(curves.get(repoId), at, curveKept)) return
    const batch = [repoId]
    for (const key of keys.value) {
      if (batch.length >= TRENDS_BATCH) break
      const id = repoOf(key)
      if (id && !batch.includes(id) && !settled(curves.get(id), at, curveKept)) batch.push(id)
    }
    for (const id of batch) remember(curves, id, { status: 'loading' })
    loadTrends(batch).then(
      (response) => {
        for (const id of batch) {
          remember(curves, id, {
            status: 'ready',
            points: response.items[id]?.points ?? [],
            metricDate: response.metric_date,
            days: response.days,
          })
        }
      },
      () => {
        for (const id of batch) remember(curves, id, { status: 'error' })
      },
    )
  }

  /** 这个仓库的速览和曲线，没取过（或该再取了）的去取 */
  const fetch = (repoId: string) => {
    fetchPeek(repoId)
    fetchCurves(repoId)
  }

  /** 没取到的（取失败、读不到 GitHub、曲线没取到）马上再取，不等半分钟 */
  const retry = (repoId: string) => {
    const peek = peeks.get(repoId)?.state
    if (peek && peek.status !== 'loading' && !peekKept(peek)) peeks.delete(repoId)
    if (curves.get(repoId)?.state.status === 'error') curves.delete(repoId)
    fetch(repoId)
  }

  const contentOf = (repoId: string): PeekContent => peeks.get(repoId)?.state ?? { status: 'loading' }
  const curveOf = (repoId: string): PeekCurveState => curves.get(repoId)?.state ?? { status: 'loading' }

  return { fetch, fetchPeek, retry, contentOf, curveOf }
}

export type ProjectPeekData = ReturnType<typeof useProjectPeekData>

export interface ProjectPeekOptions {
  /** 桌面紧凑榜单才浮；变成不能浮时收起 */
  enabled: Ref<boolean>
  /** 卡片的定位框（榜单 section） */
  frame: Ref<HTMLElement | null>
  /** 各行的父级，行上带 data-list-key */
  rows: Ref<HTMLElement | null>
  /** 这一页各行的 key，按阅读顺序；换了一批就收起 */
  keys: Ref<readonly string[]>
  /** 行的 key 换成速览查的仓库；网页收藏等没有速览的给 '' */
  repoOf: (key: string) => string
  /** 和详情栏共用的数据；不给就自己取（load、loadTrends 只在这时用） */
  data?: ProjectPeekData
  load?: (repoId: string) => Promise<GitHubProjectPeek>
  loadTrends?: (repoIds: string[]) => Promise<GitHubProjectTrendsResponse>
  now?: () => number
}

export function useProjectPeek({
  enabled,
  frame,
  rows,
  keys,
  repoOf,
  data: shared,
  load,
  loadTrends,
  now = () => Date.now(),
}: ProjectPeekOptions) {
  const data = shared ?? useProjectPeekData({ keys, repoOf, load, loadTrends, now })
  const target = ref<PeekTarget | null>(null)
  const placement = ref<PeekPlacement | null>(null)

  // 计时停稳的那一行和起点；卡片的稍后收起；刚收起的余温
  let timer: ReturnType<typeof setTimeout> | undefined
  let pending: string | null = null
  let anchor: { x: number; y: number } | null = null
  let closer: ReturnType<typeof setTimeout> | undefined
  let warmUntil = 0
  let last: { x: number; y: number } | null = null
  let live = true

  const usable = () => live && enabled.value

  const rowOf = (key: string) =>
    Array.from(rows.value?.querySelectorAll<HTMLElement>('[data-list-key]') ?? []).find((el) => el.dataset.listKey === key) ?? null

  const stopTimer = () => {
    clearTimeout(timer)
    timer = undefined
    pending = null
    anchor = null
  }
  const stopCloser = () => {
    clearTimeout(closer)
    closer = undefined
  }
  const hide = () => {
    stopCloser()
    target.value = null
    placement.value = null
  }

  /** 收起卡片、停下计时；开着卡片时返回 true（键盘流的 Esc 据此知道这一下收的是卡片）。 */
  const close = (): boolean => {
    stopTimer()
    const open = target.value !== null
    hide()
    return open
  }

  /** 离开了这一行和卡片：稍等再收，及时回来（或挪进卡片里）就不收。 */
  const closeSoon = () => {
    if (closer !== undefined || target.value === null) return
    closer = setTimeout(() => {
      closer = undefined
      warmUntil = now() + PEEK_WARM_MS
      hide()
    }, PEEK_CLOSE_GRACE)
  }

  const show = (key: string) => {
    stopTimer()
    const repoId = repoOf(key)
    const row = rowOf(key)
    const box = frame.value
    if (!usable() || !repoId || !row || !box) return
    const frameBox = box.getBoundingClientRect()
    const rowBox = row.getBoundingClientRect()
    const view = viewOf(row)
    // 榜单第一行的上沿：卡片往上长先只盖行
    const listTop = rows.value?.getBoundingClientRect().top ?? view.top
    stopCloser()
    placement.value = peekPlacement({ top: rowBox.top, bottom: rowBox.bottom }, view, frameBox.top + box.clientTop, listTop)
    target.value = { key, repoId }
    data.fetch(repoId)
  }

  const onMove = (event: PointerEvent) => {
    if (!usable() || event.pointerType !== 'mouse' || event.buttons !== 0) return
    const { clientX: x, clientY: y } = event
    // 滚动后浏览器会在原地补发移动，指针其实没动，不当成停到了新的一行上
    if (last && last.x === x && last.y === y) return
    last = { x, y }
    const el = event.target instanceof Element ? event.target : null
    const row = el?.closest<HTMLElement>('[data-list-key]') ?? null
    const key = row && rows.value?.contains(row) ? row.dataset.listKey ?? null : null
    if (target.value) {
      if (key === target.value.key) {
        // 还在（或回到了）开着卡片的那一行上
        stopCloser()
        stopTimer()
        return
      }
      closeSoon()
    }
    // 收藏、推荐、外链这些按钮上不浮：要点的是按钮
    if (key === null || !repoOf(key) || el?.closest('.project-row__actions')) {
      stopTimer()
      return
    }
    if (key === pending && anchor && Math.hypot(x - anchor.x, y - anchor.y) <= PEEK_STILL_RADIUS) return
    // 进了新的一行，或者挪远了：从这里重新计时
    clearTimeout(timer)
    pending = key
    anchor = { x, y }
    timer = setTimeout(() => show(key), target.value !== null || now() < warmUntil ? PEEK_SWITCH_DELAY : PEEK_OPEN_DELAY)
  }

  const onLeave = (event: PointerEvent) => {
    if (event.pointerType !== 'mouse') return
    stopTimer()
    closeSoon()
  }

  /** 指针挪进了卡片：留着，也不再等着换行。 */
  const hold = () => {
    stopCloser()
    stopTimer()
  }
  /** 指针离开卡片：回到这一行由行上的移动接着；去了别处就稍后收起。 */
  const release = () => closeSoon()

  const inCard = (node: EventTarget | null) => node instanceof Element && node.closest(CARD) !== null
  const busy = () => target.value !== null || timer !== undefined

  useEventListener(rows, 'pointermove', onMove, { passive: true })
  useEventListener(rows, 'pointerleave', onLeave, { passive: true })
  useEventListener(window, 'pointerdown', (event: PointerEvent) => {
    if (busy() && !inCard(event.target)) close()
  }, { capture: true, passive: true })
  useEventListener(window, 'keydown', (event: KeyboardEvent) => {
    if (!busy() || KEEP_KEYS.has(event.key) || event.ctrlKey || event.metaKey || event.altKey) return
    close()
  })
  useEventListener(window, 'focusin', (event: FocusEvent) => {
    if (target.value !== null && !inCard(event.target)) close()
  })
  // 只认挪动了榜单的滚动（页面或榜单所在的滚动框）；卡片里自己滚、别处的小滚动框不算
  useEventListener(document, 'scroll', (event: Event) => {
    if (!busy()) return
    const scroller = event.target
    const list = rows.value
    if (scroller === document || (scroller instanceof Node && list !== null && scroller.contains(list))) close()
  }, { capture: true, passive: true })
  useEventListener(window, 'blur', () => close())
  useEventListener(window, 'resize', () => close(), { passive: true })
  useEventListener(document, 'visibilitychange', () => {
    if (document.hidden) close()
  })

  watch(() => keys.value.join('\n'), () => close())
  watch(enabled, (on) => {
    if (!on) close()
  })
  // 留在 KeepAlive 里的榜单切走后不浮
  onActivated(() => { live = true })
  onDeactivated(() => {
    live = false
    close()
  })
  onBeforeUnmount(() => {
    stopTimer()
    stopCloser()
  })

  const content = computed<PeekContent | null>(() => {
    const repoId = target.value?.repoId
    return repoId ? data.contentOf(repoId) : null
  })
  const curve = computed<PeekCurveState | null>(() => {
    const repoId = target.value?.repoId
    return repoId ? data.curveOf(repoId) : null
  })

  return { target, placement, content, curve, close, hold, release }
}

export type ProjectPeek = ReturnType<typeof useProjectPeek>
