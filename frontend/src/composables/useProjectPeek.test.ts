import { mount, type VueWrapper } from '@vue/test-utils'
import { defineComponent, h, nextTick, ref } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { GitHubProjectPeek, GitHubProjectTrendsResponse } from '@/services/projects/projectApi'
import {
  PEEK_CLOSE_GRACE,
  PEEK_OPEN_DELAY,
  PEEK_SWITCH_DELAY,
  PEEK_WARM_MS,
  useProjectPeek,
  type ProjectPeek,
} from './useProjectPeek'

// jsdom 不排版：行按顺序每 100px 一行、高 80px，榜单从视口顶上开始（listTop 可以往下挪）；视口高 768px（jsdom 默认）。
const ROW = 100
const HEIGHT = 80
const indexOf = (el: Element) => Array.from(el.parentElement?.querySelectorAll('[data-list-key]') ?? []).indexOf(el)
let listTop = 0

beforeEach(() => {
  listTop = 0
  vi.useFakeTimers()
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (this: HTMLElement) {
    const top = this.dataset.listKey ? listTop + indexOf(this) * ROW : this.tagName === 'OL' ? listTop : 0
    const height = this.dataset.listKey ? HEIGHT : 0
    return { top, bottom: top + height, left: 0, right: 300, width: 300, height, x: 0, y: top, toJSON: () => ({}) } as DOMRect
  })
})

let wrapper: VueWrapper | undefined
afterEach(() => {
  wrapper?.unmount()
  wrapper = undefined
  vi.restoreAllMocks()
  vi.useRealTimers()
  document.body.innerHTML = ''
})

const peekOf = (repoId: string): GitHubProjectPeek => ({
  repo_id: repoId,
  status: 'ok',
  has_readme: true,
  readme: [`About ${repoId}`],
  readme_more: false,
  commit: null,
})

const trendsOf = (repoIds: string[]): GitHubProjectTrendsResponse => ({
  metric_date: '2026-10-02',
  previous_date: null,
  days: 30,
  items: Object.fromEntries(repoIds.map((id) => [id, { points: [{ date: '2026-10-02', stars: 7, gain: 1 }], previous_rank: null }])),
})

const KEYS = ['a', 'b', 'c', 'site', 'd', 'e', 'f']

const mountPeek = async ({ load = vi.fn(async (repoId: string) => peekOf(repoId)) } = {}) => {
  const keys = ref<string[]>(KEYS)
  const enabled = ref(true)
  const loadTrends = vi.fn(async (repoIds: string[]) => trendsOf(repoIds))
  let peek!: ProjectPeek
  const Host = defineComponent({
    setup() {
      const frame = ref<HTMLElement | null>(null)
      const rows = ref<HTMLElement | null>(null)
      // 网页收藏（site）没有速览
      peek = useProjectPeek({ enabled, frame, rows, keys, repoOf: (key) => (key === 'site' ? '' : `acme/${key}`), load, loadTrends })
      return () => h('section', { ref: frame }, [
        h('ol', { ref: rows }, keys.value.map((key) => h('li', { key, 'data-list-key': key }, [
          h('span', { class: 'name' }, key),
          h('div', { class: 'project-row__actions' }, [h('button', { type: 'button' }, 'star')]),
        ]))),
        peek.target.value
          ? h('aside', { 'data-project-peek': '' }, [h('div', { class: 'scroll' }, [h('a', { href: '#readme' }, 'README')])])
          : null,
        h('div', { class: 'elsewhere' }, [h('input', { id: 'field' })]),
      ])
    },
  })
  wrapper = mount(Host, { attachTo: document.body })
  // 行上的监听在挂载后的那一拍才挂上
  await nextTick()
  const row = (key: string) => document.querySelector<HTMLElement>(`[data-list-key="${key}"]`)!
  const rowsEl = () => document.querySelector<HTMLElement>('ol')!
  const card = () => document.querySelector<HTMLElement>('[data-project-peek]')
  return { keys, enabled, load, loadTrends, row, rowsEl, card, get peek() { return peek } }
}

const pointer = (type: string, target: EventTarget, x: number, y: number, { pointerType = 'mouse', buttons = 0 } = {}) => {
  const event = new MouseEvent(type, { clientX: x, clientY: y, buttons, bubbles: type !== 'pointerleave' })
  Object.defineProperty(event, 'pointerType', { value: pointerType })
  target.dispatchEvent(event)
}
const hover = (target: Element, x: number, y: number, init?: { pointerType?: string; buttons?: number }) =>
  pointer('pointermove', target, x, y, init)
const press = (key: string, init: KeyboardEventInit = {}) =>
  window.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true, ...init }))
const wait = (ms: number) => vi.advanceTimersByTimeAsync(ms)

/** 停在某一行上直到卡片浮出来 */
const openOn = async (list: Awaited<ReturnType<typeof mountPeek>>, key: string, x = 40, y = 20) => {
  hover(list.row(key).querySelector('.name')!, x, y)
  await wait(PEEK_OPEN_DELAY)
  await nextTick()
}

describe('useProjectPeek', () => {
  it('opens under a row the pointer rests on for half a second and fetches its peek and the page’s curves at once', async () => {
    const list = await mountPeek()
    hover(list.row('b').querySelector('.name')!, 40, 120)
    await wait(PEEK_OPEN_DELAY - 1)
    expect(list.peek.target.value).toBeNull()
    expect(list.load).not.toHaveBeenCalled()

    await wait(1)
    expect(list.peek.target.value).toEqual({ key: 'b', repoId: 'acme/b' })
    // b 的下边 180、留 6px 缝；视口里下面还剩 768 − 180 − 6
    expect(list.peek.placement.value).toEqual({ top: 186, above: false, maxHeight: 582 })
    expect(list.load.mock.calls).toEqual([['acme/b']])
    // 看着的排第一，再按榜单顺序带上这一页其余的仓库，网页收藏不算
    expect(list.loadTrends.mock.calls).toEqual([[['acme/b', 'acme/a', 'acme/c', 'acme/d', 'acme/e', 'acme/f']]])

    await nextTick()
    expect(list.peek.content.value).toEqual({ status: 'ready', peek: peekOf('acme/b') })
    expect(list.peek.curve.value).toEqual({
      status: 'ready',
      points: [{ date: '2026-10-02', stars: 7, gain: 1 }],
      metricDate: '2026-10-02',
      days: 30,
    })
    expect(list.card()).not.toBeNull()
  })

  it('shows the loading state until GitHub answers', async () => {
    let answer!: (peek: GitHubProjectPeek) => void
    const list = await mountPeek({ load: vi.fn(() => new Promise<GitHubProjectPeek>((resolve) => { answer = resolve })) })
    await openOn(list, 'a')
    expect(list.peek.content.value).toEqual({ status: 'loading' })
    answer(peekOf('acme/a'))
    await wait(0)
    expect(list.peek.content.value).toEqual({ status: 'ready', peek: peekOf('acme/a') })
  })

  it('rises over a row near the bottom of the view, as tall as the room above it', async () => {
    const list = await mountPeek()
    // f 是第 7 行：600–680，下面只剩 82px
    await openOn(list, 'f', 40, 620)
    expect(list.peek.placement.value).toEqual({ top: 594, above: true, maxHeight: 594 })
  })

  it('rises over rows rather than the page header, unless only the header leaves it room', async () => {
    // 页头、搜索框和表头占着视口上面 250px：e 是第 6 行，750–830，下面没地方了，上面的行够高
    listTop = 250
    const list = await mountPeek()
    await openOn(list, 'e', 40, 770)
    expect(list.peek.placement.value).toEqual({ top: 744, above: true, maxHeight: 750 - 250 - 6 })

    // c 是第 3 行，450–530：上面的行只剩 194、下面 232，这才盖过页头
    list.peek.close()
    await openOn(list, 'c', 40, 470)
    expect(list.peek.placement.value).toEqual({ top: 444, above: true, maxHeight: 444 })
  })

  it('starts the wait over while the pointer travels, but lets a small tremble pass', async () => {
    const list = await mountPeek()
    const name = list.row('a').querySelector('.name')!
    hover(name, 40, 20)
    await wait(300)
    hover(name, 44, 24)
    await wait(PEEK_OPEN_DELAY - 300)
    expect(list.peek.target.value?.key).toBe('a')

    list.peek.close()
    hover(name, 40, 20)
    await wait(300)
    hover(name, 60, 20)
    await wait(PEEK_OPEN_DELAY - 300)
    expect(list.peek.target.value).toBeNull()
    await wait(300)
    expect(list.peek.target.value?.key).toBe('a')
  })

  it('never opens over the row’s buttons, on a web page, for touch or a pen, or while a button is held', async () => {
    const list = await mountPeek()
    hover(list.row('a').querySelector('button')!, 280, 20)
    hover(list.row('a').querySelector('button')!, 284, 30)
    await wait(PEEK_OPEN_DELAY * 2)
    hover(list.row('site').querySelector('.name')!, 40, 320)
    await wait(PEEK_OPEN_DELAY * 2)
    hover(list.row('b').querySelector('.name')!, 40, 120, { pointerType: 'touch' })
    await wait(PEEK_OPEN_DELAY * 2)
    hover(list.row('b').querySelector('.name')!, 41, 121, { pointerType: 'pen' })
    await wait(PEEK_OPEN_DELAY * 2)
    hover(list.row('b').querySelector('.name')!, 42, 122, { buttons: 1 })
    await wait(PEEK_OPEN_DELAY * 2)
    expect(list.peek.target.value).toBeNull()
    expect(list.load).not.toHaveBeenCalled()
  })

  it('switches rows after a short pause while a card is out, and again just after it closed', async () => {
    const list = await mountPeek()
    await openOn(list, 'a')
    hover(list.row('b').querySelector('.name')!, 40, 120)
    await wait(PEEK_SWITCH_DELAY - 1)
    expect(list.peek.target.value?.key).toBe('a')
    await wait(1)
    expect(list.peek.target.value?.key).toBe('b')

    // 离开榜单：稍等收起，刚收起时停到别的行上照样稍停就浮
    pointer('pointerleave', list.rowsEl(), 400, 120)
    await wait(PEEK_CLOSE_GRACE)
    expect(list.peek.target.value).toBeNull()
    hover(list.row('c').querySelector('.name')!, 40, 220)
    await wait(PEEK_SWITCH_DELAY)
    expect(list.peek.target.value?.key).toBe('c')

    // 收起久了就回到停稳半秒
    pointer('pointerleave', list.rowsEl(), 400, 220)
    await wait(PEEK_CLOSE_GRACE + PEEK_WARM_MS)
    hover(list.row('d').querySelector('.name')!, 40, 420)
    await wait(PEEK_SWITCH_DELAY)
    expect(list.peek.target.value).toBeNull()
    await wait(PEEK_OPEN_DELAY - PEEK_SWITCH_DELAY)
    expect(list.peek.target.value?.key).toBe('d')
  })

  it('stays while the pointer comes back to its row or moves into the card, and closes once it has left both', async () => {
    const list = await mountPeek()
    await openOn(list, 'a')
    // 擦过下一行又回来
    hover(list.row('b').querySelector('.name')!, 40, 120)
    hover(list.row('a').querySelector('.name')!, 40, 60)
    await wait(1000)
    expect(list.peek.target.value?.key).toBe('a')

    // 穿过下一行进了卡片
    hover(list.row('b').querySelector('.name')!, 200, 90)
    pointer('pointerleave', list.rowsEl(), 200, 92)
    list.peek.hold()
    await wait(1000)
    expect(list.peek.target.value?.key).toBe('a')

    list.peek.release()
    await wait(PEEK_CLOSE_GRACE - 1)
    expect(list.peek.target.value?.key).toBe('a')
    await wait(1)
    expect(list.peek.target.value).toBeNull()
  })

  it('closes on keys other than modifiers, Tab and Esc, which the keyboard flow hands over through close()', async () => {
    const list = await mountPeek()
    expect(list.peek.close()).toBe(false)
    await openOn(list, 'a')
    for (const key of ['Shift', 'Control', 'Alt', 'Meta', 'Tab', 'Escape']) press(key)
    press('c', { ctrlKey: true })
    expect(list.peek.target.value?.key).toBe('a')
    press('j')
    expect(list.peek.target.value).toBeNull()

    await openOn(list, 'b', 40, 120)
    expect(list.peek.close()).toBe(true)
    expect(list.peek.target.value).toBeNull()
  })

  it('closes on a press outside the card, on focus leaving for elsewhere, on scrolling the list and on leaving the window', async () => {
    const list = await mountPeek()
    await openOn(list, 'a')
    pointer('pointerdown', list.card()!.querySelector('a')!, 300, 100)
    list.card()!.querySelector('a')!.focus()
    // 卡片里自己滚、别处的滚动框滚动都不算
    list.card()!.querySelector('.scroll')!.dispatchEvent(new Event('scroll'))
    document.querySelector('.elsewhere')!.dispatchEvent(new Event('scroll'))
    expect(list.peek.target.value?.key).toBe('a')
    pointer('pointerdown', list.row('c'), 40, 220)
    expect(list.peek.target.value).toBeNull()

    await openOn(list, 'b', 40, 120)
    document.querySelector<HTMLInputElement>('#field')!.focus()
    expect(list.peek.target.value).toBeNull()

    await openOn(list, 'c', 40, 220)
    document.body.dispatchEvent(new Event('scroll'))
    expect(list.peek.target.value).toBeNull()

    await openOn(list, 'a', 40, 30)
    document.dispatchEvent(new Event('scroll'))
    expect(list.peek.target.value).toBeNull()

    await openOn(list, 'b', 40, 130)
    window.dispatchEvent(new Event('blur'))
    expect(list.peek.target.value).toBeNull()
  })

  it('does not take the pointer left still under a scrolled list for a new rest', async () => {
    const list = await mountPeek()
    await openOn(list, 'a', 40, 20)
    document.dispatchEvent(new Event('scroll'))
    expect(list.peek.target.value).toBeNull()
    // 列表滚过之后浏览器在原地补发的移动：落到了 b 上，但指针没动
    hover(list.row('b').querySelector('.name')!, 40, 20)
    await wait(PEEK_OPEN_DELAY * 2)
    expect(list.peek.target.value).toBeNull()
    hover(list.row('b').querySelector('.name')!, 41, 21)
    await wait(PEEK_OPEN_DELAY)
    expect(list.peek.target.value?.key).toBe('b')
  })

  it('closes when the page brings other rows or the chart is switched off, and stays shut while off', async () => {
    const list = await mountPeek()
    await openOn(list, 'a')
    list.keys.value = ['b', 'c']
    await nextTick()
    expect(list.peek.target.value).toBeNull()

    await openOn(list, 'b', 40, 30)
    list.enabled.value = false
    await nextTick()
    expect(list.peek.target.value).toBeNull()
    hover(list.row('c').querySelector('.name')!, 40, 120)
    await wait(PEEK_OPEN_DELAY * 2)
    expect(list.peek.target.value).toBeNull()
  })

  it('keeps what it fetched for ten minutes and tries again thirty seconds after a failure', async () => {
    const load = vi.fn(async (repoId: string) => {
      if (repoId === 'acme/c') throw new Error('rate limited')
      return peekOf(repoId)
    })
    const list = await mountPeek({ load })
    await openOn(list, 'a', 40, 20)
    await openOn(list, 'b', 40, 120)
    await openOn(list, 'a', 40, 21)
    expect(load.mock.calls).toEqual([['acme/a'], ['acme/b']])
    // b 的曲线跟着 a 那一批取到了
    expect(list.loadTrends).toHaveBeenCalledTimes(1)

    await openOn(list, 'c', 40, 220)
    expect(list.peek.content.value).toEqual({ status: 'error' })
    list.peek.close()
    await openOn(list, 'c', 40, 221)
    expect(load).toHaveBeenCalledTimes(3)
    list.peek.close()
    await wait(30_000)
    await openOn(list, 'c', 40, 222)
    expect(load).toHaveBeenCalledTimes(4)

    list.peek.close()
    await wait(10 * 60_000)
    await openOn(list, 'a', 40, 22)
    expect(load).toHaveBeenCalledTimes(5)
    expect(load).toHaveBeenLastCalledWith('acme/a')
    expect(list.loadTrends).toHaveBeenCalledTimes(2)
  })
})
