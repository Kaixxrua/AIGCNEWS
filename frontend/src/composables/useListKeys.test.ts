import { mount, type VueWrapper } from '@vue/test-utils'
import { defineComponent, h, nextTick, ref } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { i18n } from '@/i18n'
import { showToast } from '@/composables/useToast'
import { LIST_KEYS_HINT, useListKeys, type ListKeys, type ListKeysOptions } from './useListKeys'

vi.mock('@/composables/useToast', () => ({ showToast: vi.fn() }))

// jsdom 不排版：条目按顺序每 100px 一条、高 80px，scrolled 是列表往上滚走了多少；视口高 768px（jsdom 默认）。
// scrollIntoView 按 nearest 把条目滚进视野。
const ROW = 100
const HEIGHT = 80
let scrolled = 0
const indexOf = (el: Element) => Array.from(el.parentElement?.querySelectorAll('[data-list-key]') ?? []).indexOf(el)
const topOf = (el: Element) => indexOf(el) * ROW - scrolled

beforeEach(() => {
  scrolled = 0
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (this: HTMLElement) {
    const top = indexOf(this) < 0 ? 0 : topOf(this)
    return { top, bottom: top + HEIGHT, left: 0, right: 300, width: 300, height: HEIGHT, x: 0, y: top, toJSON: () => ({}) } as DOMRect
  })
  HTMLElement.prototype.scrollIntoView = function (this: HTMLElement) {
    const top = topOf(this)
    if (top < 0) scrolled += top
    else if (top + HEIGHT > window.innerHeight) scrolled += top + HEIGHT - window.innerHeight
  }
})

let wrapper: VueWrapper | undefined
afterEach(() => {
  wrapper?.unmount()
  wrapper = undefined
  vi.restoreAllMocks()
  vi.mocked(showToast).mockClear()
  localStorage.clear()
  document.body.innerHTML = ''
})

const mountList = (initial: string[], options: Partial<ListKeysOptions> = {}) => {
  const order = ref<string[]>(initial)
  const enabled = ref(true)
  const calls = { open: [] as string[], toggle: [] as string[], passed: [] as string[], edge: [] as number[] }
  let keys!: ListKeys
  const List = defineComponent({
    setup() {
      const root = ref<HTMLElement | null>(null)
      keys = useListKeys({
        enabled,
        root,
        keys: order,
        open: (key) => calls.open.push(key),
        toggle: (key) => calls.toggle.push(key),
        passed: (key) => calls.passed.push(key),
        edge: (direction) => { calls.edge.push(direction); return false },
        ...options,
      })
      return () => h('div', [
        h('div', { ref: root }, order.value.map((key) => h('article', { key, 'data-list-key': key, class: { 'is-cursor': keys.isCursor(key) } }, [
          key,
          h('button', { type: 'button' }, 'go'),
        ]))),
        h('input', { id: 'field' }),
      ])
    },
  })
  wrapper = mount(List, { attachTo: document.body, global: { plugins: [i18n] } })
  const item = (key: string) => document.querySelector<HTMLElement>(`[data-list-key="${key}"]`)!
  return { order, enabled, calls, keys, item }
}

const press = (key: string, init: KeyboardEventInit = {}, target: EventTarget = window) => {
  const event = new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true, ...init })
  target.dispatchEvent(event)
  return event
}

describe('useListKeys', () => {
  it('lights the first item in view, then walks down and up in reading order, marking the ones passed', async () => {
    const { keys, calls, item } = mountList(['a', 'b', 'c'])

    expect(press('j').defaultPrevented).toBe(true)
    expect(keys.cursor.value).toBe('a')
    expect(keys.isCursor('a')).toBe(true)
    expect(document.activeElement).toBe(item('a'))
    expect(item('a').getAttribute('tabindex')).toBe('-1')
    expect(calls.passed).toEqual([])

    press('j')
    expect(keys.cursor.value).toBe('b')
    expect(document.activeElement).toBe(item('b'))
    press('k')
    expect(keys.cursor.value).toBe('a')
    expect(calls.passed).toEqual(['a'])
    await nextTick()
    expect(item('a').classList.contains('is-cursor')).toBe(true)
    expect(item('b').classList.contains('is-cursor')).toBe(false)
  })

  it('scrolls the item it moves to into view', () => {
    const { keys } = mountList(Array.from({ length: 12 }, (_, index) => `t${index}`))
    for (let step = 0; step < 9; step += 1) press('j')
    expect(keys.cursor.value).toBe('t8')
    // 第 9 条（800–880px）滚到视野底边以内
    expect(scrolled).toBe(8 * ROW + HEIGHT - window.innerHeight)
  })

  it('starts again from what is in view once the cursor has been scrolled away', () => {
    const { keys, calls } = mountList(['a', 'b', 'c', 'd', 'e', 'f'])
    press('j')
    expect(keys.cursor.value).toBe('a')
    scrolled = 250 // a、b 滚出视野，c 只露出下半截，d 是第一条整条在视野里的
    press('j')
    expect(keys.cursor.value).toBe('d')
    expect(calls.passed).toEqual([])
  })

  it('hands the ends to edge and lands on the new page when edge takes them', async () => {
    let flip: (direction: 1 | -1) => boolean = () => false
    const { keys, calls, order } = mountList(['a', 'b'], { edge: (direction) => flip(direction) })
    press('j')
    press('j')
    press('j')
    expect(keys.cursor.value).toBe('b')
    expect(calls.passed).toEqual(['a', 'b'])

    flip = () => { order.value = ['p', 'q', 'r']; return true }
    press('j')
    await nextTick()
    await nextTick()
    expect(keys.cursor.value).toBe('p')

    flip = () => { order.value = ['x', 'y']; return true }
    press('k')
    await nextTick()
    await nextTick()
    expect(keys.cursor.value).toBe('y')
  })

  it('lights a cursor on the first press of o or x, then acts on it', () => {
    const { keys, calls } = mountList(['a', 'b'])
    press('o')
    expect(calls.open).toEqual([])
    expect(keys.cursor.value).toBe('a')
    expect(keys.shown.value).toBe(true)
    press('o')
    press('x')
    expect(calls.open).toEqual(['a'])
    expect(calls.toggle).toEqual(['a'])
    // 没交代的键（这里是 s）不拦
    expect(press('s').defaultPrevented).toBe(false)
  })

  it('takes Enter only on the cursor item itself, not on a button inside it', () => {
    const { calls, item } = mountList(['a', 'b'])
    press('j')
    press('Enter', {}, item('a'))
    expect(calls.open).toEqual(['a'])
    press('Enter', {}, item('a').querySelector('button')!)
    expect(calls.open).toEqual(['a'])
  })

  it('follows a click or Tab to an item quietly, and acts on it at once', () => {
    const { keys, calls, item } = mountList(['a', 'b', 'c'])
    item('c').dispatchEvent(new MouseEvent('pointerdown', { bubbles: true }))
    expect(keys.cursor.value).toBe('c')
    expect(keys.shown.value).toBe(false)
    press('o')
    expect(calls.open).toEqual(['c'])
    expect(keys.shown.value).toBe(true)

    item('b').querySelector('button')!.dispatchEvent(new FocusEvent('focusin', { bubbles: true }))
    expect(keys.cursor.value).toBe('b')
    press('j')
    expect(keys.cursor.value).toBe('c')
  })

  it('leaves the keys to fields, open modals and modified presses', () => {
    const { keys } = mountList(['a', 'b'])
    const field = document.getElementById('field')!
    expect(press('j', {}, field).defaultPrevented).toBe(false)
    press('j', { ctrlKey: true })
    expect(keys.cursor.value).toBeNull()

    const modal = document.createElement('div')
    modal.setAttribute('aria-modal', 'true')
    modal.getClientRects = () => [{}] as unknown as DOMRectList
    document.body.append(modal)
    press('j')
    press('?')
    expect(keys.cursor.value).toBeNull()
    expect(keys.help.value).toBe(false)
  })

  it('opens the shortcut sheet on ?, and closes it on Esc before hiding the cursor', () => {
    const { keys, item } = mountList(['a', 'b'])
    press('j')
    press('?')
    expect(keys.help.value).toBe(true)
    press('Escape')
    expect(keys.help.value).toBe(false)
    expect(keys.shown.value).toBe(true)
    press('Escape')
    expect(keys.shown.value).toBe(false)
    expect(keys.cursor.value).toBeNull()
    expect(document.activeElement).not.toBe(item('a'))
  })

  it('tells the list where the keys took the cursor, but not where a click or the list itself put it', () => {
    const reached: string[] = []
    const { keys, item } = mountList(['a', 'b', 'c'], { reached: (key) => reached.push(key) })
    press('j')
    press('j')
    press('k')
    expect(reached).toEqual(['a', 'b', 'a'])
    item('c').dispatchEvent(new MouseEvent('pointerdown', { bubbles: true }))
    keys.setCursor('b', { reveal: true })
    expect(reached).toEqual(['a', 'b', 'a'])
  })

  it('lets the list close what it has open on Esc before the cursor goes', () => {
    let open = true
    const escape = vi.fn(() => {
      if (!open) return false
      open = false
      return true
    })
    const { keys } = mountList(['a', 'b'], { escape })
    press('j')
    press('?')
    press('Escape')
    expect(escape).not.toHaveBeenCalled()
    press('Escape')
    expect(escape).toHaveBeenCalledTimes(1)
    expect(keys.shown.value).toBe(true)
    press('Escape')
    expect(keys.shown.value).toBe(false)

    // 开着弹窗时 Esc 归弹窗
    open = true
    const modal = document.createElement('div')
    modal.setAttribute('aria-modal', 'true')
    modal.getClientRects = () => [{}] as unknown as DOMRectList
    document.body.append(modal)
    press('Escape')
    expect(escape).toHaveBeenCalledTimes(2)
    expect(open).toBe(true)
  })

  it('lets the list move the cursor itself and puts the focus back on it', async () => {
    const { keys, item } = mountList(Array.from({ length: 12 }, (_, index) => `t${index}`))
    keys.setCursor('t10', { reveal: true, focus: true })
    expect(keys.cursor.value).toBe('t10')
    await nextTick()
    expect(document.activeElement).toBe(item('t10'))
    expect(topOf(item('t10')) + HEIGHT).toBeLessThanOrEqual(window.innerHeight)

    // 由列表挪的光标不亮；焦点放回去时才亮出来
    expect(keys.shown.value).toBe(false)
    item('t10').blur()
    expect(keys.focusCursor()).toBe(true)
    expect(keys.shown.value).toBe(true)
    expect(document.activeElement).toBe(item('t10'))
  })

  it('drops the cursor when its item leaves the list, and stops listening when switched off', async () => {
    const { keys, order, enabled } = mountList(['a', 'b', 'c'])
    press('j')
    order.value = ['b', 'c']
    await nextTick()
    expect(keys.cursor.value).toBeNull()
    expect(keys.shown.value).toBe(false)

    press('j')
    expect(keys.cursor.value).toBe('b')
    enabled.value = false
    await nextTick()
    expect(keys.shown.value).toBe(false)
    press('j')
    expect(keys.cursor.value).toBeNull()
  })

  it('hints once per browser that the list can be read with the keyboard', async () => {
    vi.useFakeTimers()
    try {
      mountList(['a'])
      vi.advanceTimersByTime(LIST_KEYS_HINT.delayMs)
      expect(showToast).toHaveBeenCalledTimes(1)
      expect(vi.mocked(showToast).mock.calls[0]![0]).toMatch(/j/)
      expect(localStorage.getItem(LIST_KEYS_HINT.storageKey)).toBe('1')

      wrapper!.unmount()
      wrapper = undefined
      mountList(['a'])
      vi.advanceTimersByTime(LIST_KEYS_HINT.delayMs * 2)
      expect(showToast).toHaveBeenCalledTimes(1)
    } finally {
      vi.useRealTimers()
    }
  })
})
