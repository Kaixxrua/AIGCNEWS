import { nextTick, onActivated, onBeforeUnmount, onDeactivated, ref, watch, type Ref } from 'vue'
import { useEventListener } from '@vueuse/core'
import { useI18n } from 'vue-i18n'
import { showToast } from '@/composables/useToast'
import { prefersReducedMotion } from '@/motion/motion'
import { firstInView, isModalOpen, isTypingTarget, listKeyAction, stepKey, type Span } from '@/features/keyboard/listKeys'

/**
 * 列表键盘流：j / k 在条目之间上下移动，o（焦点停在条目上时也可按回车）打开，s 收藏，x 折叠或展开，
 * ? 开合快捷键表，Esc 收起光标。推文墙与简报条目用同一套键位，各列表只交代条目的阅读顺序和每个键做什么。
 *
 * 条目元素带 data-list-key；isCursor 给出光标落在哪条，列表根上的 v-indicator 让荧光标记滑过去。
 * 移动时把条目滚进视野（让开顶部与底部遮挡的距离由条目的 scroll-margin 定，比视野还高的条目对齐顶边），
 * 并把焦点放到条目上，读屏会念出来，Tab 也从这里接着走。光标不在视野里（用滚轮滚远了）时，
 * 下一次按键从视野里第一条起，不把页面拽回去。用鼠标点了哪条、Tab 走到哪条，光标就悄悄落到那条，
 * 再按 j 从它往下，按 o、s、x 直接作用在它上面。还没有光标时，o、s、x 第一下只把光标亮在视野里第一条，免得对着看不见的条目动手。
 */
export interface ListKeysOptions {
  enabled: Ref<boolean>
  root: Ref<HTMLElement | null>
  /** 条目的 key，按阅读顺序。 */
  keys: Ref<readonly string[]>
  open?: (key: string) => void
  save?: (key: string) => void
  toggle?: (key: string) => void
  /** 光标从这条往下走了：读过了。 */
  passed?: (key: string) => void
  /** 光标被键盘挪到了这条（j / k，或 o、s、x 先点亮的那条）；鼠标点到、列表自己挪的不算。 */
  reached?: (key: string) => void
  /** Esc 先交给列表收起它自己开着的东西（如宽屏的详情栏）：收了返回 true，这一下不再收光标。 */
  escape?: () => boolean
  /** 在头尾再往外走（翻页）：接手了返回 true，列表换成新一页后光标落到它的头或尾。 */
  edge?: (direction: 1 | -1) => boolean
}

export const LIST_KEYS_HINT = { storageKey: 'list_keys_hint', delayMs: 1500 }

const scrollParent = (el: HTMLElement): HTMLElement | null => {
  for (let node = el.parentElement; node; node = node.parentElement) {
    if (/(auto|scroll|overlay)/.test(getComputedStyle(node).overflowY) && node.scrollHeight > node.clientHeight) return node
  }
  return null
}

/** 条目看得见的那段视野：最近的滚动容器，扣掉条目 scroll-margin 让出的上下遮挡（报头、页脚）。 */
export const viewOf = (el: HTMLElement): Span => {
  const scroller = scrollParent(el)
  const frame = scroller ? scroller.getBoundingClientRect() : { top: 0, bottom: window.innerHeight }
  const style = getComputedStyle(el)
  return { top: frame.top + (parseFloat(style.scrollMarginTop) || 0), bottom: frame.bottom - (parseFloat(style.scrollMarginBottom) || 0) }
}

const spanOf = (el: HTMLElement): Span => {
  const box = el.getBoundingClientRect()
  return { top: box.top, bottom: box.bottom }
}

const inView = (el: HTMLElement | null) => {
  if (!el) return false
  const box = spanOf(el)
  const view = viewOf(el)
  return box.bottom > view.top && box.top < view.bottom
}

export function useListKeys(options: ListKeysOptions) {
  const { t } = useI18n()
  const cursor = ref<string | null>(null)
  const shown = ref(false)
  const help = ref(false)
  let pendingEdge: 1 | -1 | 0 = 0
  let live = true

  const items = () => Array.from(options.root.value?.querySelectorAll<HTMLElement>('[data-list-key]') ?? [])
  const element = (key: string | null) => (key == null ? null : items().find((el) => el.dataset.listKey === key) ?? null)
  const current = () => (cursor.value != null && options.keys.value.includes(cursor.value) ? cursor.value : null)

  const reveal = (el: HTMLElement, focus: boolean) => {
    const view = viewOf(el)
    const box = spanOf(el)
    el.scrollIntoView?.({ block: box.bottom - box.top > view.bottom - view.top ? 'start' : 'nearest', behavior: prefersReducedMotion() ? 'auto' : 'smooth' })
    if (!focus) return
    if (!el.hasAttribute('tabindex')) el.setAttribute('tabindex', '-1')
    el.focus({ preventScroll: true })
  }

  const place = (key: string, { focus = true } = {}) => {
    cursor.value = key
    shown.value = true
    const el = element(key)
    if (el) reveal(el, focus)
    options.reached?.(key)
  }

  /** 收起光标；焦点还停在光标那条上时一并移走，不留一圈看不出来由的焦点框。 */
  const hide = () => {
    const el = element(cursor.value)
    if (el && document.activeElement === el) el.blur()
    cursor.value = null
    shown.value = false
  }

  /** 视野里按阅读顺序的第一条；视野里一条都没有时，往下走取第一条、往上走取最后一条。 */
  const startKey = (direction: 1 | -1): string | null => {
    const keys = options.keys.value
    const byKey = new Map(items().map((el) => [el.dataset.listKey ?? '', el]))
    const sample = byKey.values().next().value
    const visible = sample
      ? firstInView(keys, (key) => { const el = byKey.get(key); return el ? spanOf(el) : null }, viewOf(sample))
      : null
    return visible ?? (direction > 0 ? keys[0] : keys[keys.length - 1]) ?? null
  }

  /** 光标往后（1）或往前（-1）走一条，返回落到的 key；走到头时不动（交给 edge 翻页），返回 null。 */
  const move = (direction: 1 | -1): string | null => {
    pendingEdge = 0
    if (!options.keys.value.length) return null
    const from = current()
    if (from == null || !inView(element(from))) {
      const start = startKey(direction)
      if (start != null) place(start)
      return start
    }
    if (direction > 0) options.passed?.(from)
    const next = stepKey(options.keys.value, from, direction)
    if (next == null) {
      shown.value = true
      if (options.edge?.(direction)) pendingEdge = direction
      return null
    }
    place(next)
    return next
  }

  /** o、s、x 作用的条目：在视野里的光标（亮出来）；没有光标或它不在视野里时，先把光标亮在视野里第一条，这一下不动手。 */
  const target = (): string | null => {
    const key = current()
    if (key != null && inView(element(key))) {
      shown.value = true
      return key
    }
    const start = startKey(1)
    if (start != null) place(start)
    return null
  }

  /**
   * 由列表自己挪光标（推文详情里换了一条、收起折叠时落回领头那条）。reveal 时等列表画好（可能刚翻了页）再滚进视野，
   * focus 时把焦点也放过去。
   */
  const setCursor = (key: string, { reveal: scroll = false, focus = false } = {}) => {
    cursor.value = key
    if (!scroll && !focus) return
    void nextTick(() => {
      const el = cursor.value === key ? element(key) : null
      if (el) reveal(el, focus)
    })
  }

  /** 光标亮出来、焦点放回那条（关掉浮层后接着从这里走）；没有光标时为 false。 */
  const focusCursor = (): boolean => {
    const el = element(current())
    if (!el) return false
    shown.value = true
    reveal(el, true)
    return true
  }

  const isCursor = (key: string) => shown.value && cursor.value === key

  const onKeydown = (event: KeyboardEvent) => {
    if (!live || !options.enabled.value) return
    const action = listKeyAction(event)
    if (!action || isTypingTarget(event.target)) return
    if (action === 'help') {
      if (isModalOpen()) return
      event.preventDefault()
      help.value = !help.value
      return
    }
    if (action === 'escape') {
      // 先关快捷键表，再收列表自己开着的东西，最后收光标；都不拦 Esc，读报态照样把 dock 叫回来。
      if (help.value) help.value = false
      else if (!isModalOpen() && !options.escape?.() && shown.value) hide()
      return
    }
    if (isModalOpen() || !options.keys.value.length) return
    if (action === 'next' || action === 'prev') {
      event.preventDefault()
      move(action === 'next' ? 1 : -1)
      return
    }
    // 回车只在焦点停在光标那条本身时当「打开」，条目里的按钮、链接照常。
    if (event.key === 'Enter' && (current() == null || event.target !== element(current()))) return
    const act = action === 'open' ? options.open : action === 'save' ? options.save : options.toggle
    if (!act) return
    event.preventDefault()
    const key = target()
    if (key != null) act(key)
  }

  /** 点了、Tab 到了哪条，光标悄悄跟过去。 */
  const follow = (event: Event) => {
    if (!live || !options.enabled.value) return
    const el = (event.target as Element | null)?.closest?.<HTMLElement>('[data-list-key]')
    if (el && options.root.value?.contains(el)) cursor.value = el.dataset.listKey ?? null
  }

  useEventListener(window, 'keydown', onKeydown)
  useEventListener(window, 'pointerdown', follow, { capture: true, passive: true })
  useEventListener(window, 'focusin', follow)

  watch(options.keys, (keys) => {
    if (pendingEdge && keys.length) {
      // 翻到了新的一页：等它画出来再落光标、滚动与聚焦。
      const key = (pendingEdge > 0 ? keys[0] : keys[keys.length - 1])!
      pendingEdge = 0
      void nextTick(() => place(key))
      return
    }
    if (cursor.value != null && !keys.includes(cursor.value)) {
      cursor.value = null
      shown.value = false
    }
  })
  watch(options.enabled, (on) => {
    if (on) return
    hide()
    help.value = false
  })

  // 第一次在这台浏览器的桌面列表上，提示一次可以用键盘。
  let hintTimer: ReturnType<typeof setTimeout> | undefined
  watch([options.enabled, () => options.keys.value.length > 0], ([on, filled]) => {
    if (!on || !filled || hintTimer !== undefined) return
    try {
      if (localStorage.getItem(LIST_KEYS_HINT.storageKey)) return
    } catch {
      return
    }
    hintTimer = setTimeout(() => {
      if (!live || !options.enabled.value || !options.keys.value.length) return
      try {
        localStorage.setItem(LIST_KEYS_HINT.storageKey, '1')
      } catch {
        // 记不下就下次再提示
      }
      showToast(t('listKeys.hint'))
    }, LIST_KEYS_HINT.delayMs)
  }, { immediate: true })

  onBeforeUnmount(() => clearTimeout(hintTimer))
  // 留在 KeepAlive 里的列表切走后不接键。
  onActivated(() => { live = true })
  onDeactivated(() => {
    live = false
    hide()
    help.value = false
  })

  return { cursor, shown, help, isCursor, move, setCursor, focusCursor }
}

export type ListKeys = ReturnType<typeof useListKeys>
