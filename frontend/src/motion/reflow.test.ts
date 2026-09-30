import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { defineComponent, h, withDirectives, type PropType } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { vReflow } from './reflow'
import { installFakeAnimations, stubLayout, stubReducedMotion, type FakeAnimations } from './testing'

enableAutoUnmount(afterEach)

interface Tile { key: string; x: number; y: number }

// 一面 600px 宽的墙，每张卡 200×100，按给定坐标摆放（相当于瀑布流排好之后的结果）。
const Wall = defineComponent({
  props: {
    tiles: { type: Array as PropType<Tile[]>, required: true },
    wallKey: { type: String, required: true },
    from: { type: Object as PropType<{ x?: number; y?: number }>, default: () => ({}) },
  },
  setup(props) {
    return () => withDirectives(
      h('div', { class: 'wall', 'data-box': '0 0 600 3000' }, props.tiles.map((tile) =>
        h('article', { key: tile.key, 'data-reflow-key': tile.key, 'data-box': `${tile.x} ${tile.y} 200 100` }, tile.key))),
      [[vReflow, { key: props.wallKey, ...props.from }]],
    )
  },
})

const row = (keys: string, y = 0): Tile[] => keys.split('').map((key, index) => ({ key, x: index * 200, y }))

let fakes: FakeAnimations
let restoreLayout: () => void

const mountWall = (tiles: Tile[], wallKey = 'p1') => {
  const wrapper = mount(Wall, { props: { tiles, wallKey }, attachTo: document.body })
  return { wrapper, wall: wrapper.element as HTMLElement }
}
const card = (wall: HTMLElement, key: string) => wall.querySelector<HTMLElement>(`[data-reflow-key="${key}"]`)!
const delayOf = (el: Element, id: string) => fakes.on(el, id)[0]?.options.delay

describe('v-reflow', () => {
  beforeEach(() => {
    fakes = installFakeAnimations()
    restoreLayout = stubLayout()
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    fakes.restore()
    restoreLayout()
  })

  it('墙刚出现时由近及远依次浮现，最晚 0.2 秒全部起步，视口外的不动', () => {
    const { wall } = mountWall([
      { key: 'a', x: 0, y: 0 },
      { key: 'b', x: 200, y: 0 },
      { key: 'c', x: 400, y: 300 },
      { key: 'd', x: 400, y: 900 },
      { key: 'e', x: 0, y: 1000 },
    ])
    expect(delayOf(card(wall, 'a'), 'reflow-fade')).toBe(0)
    expect(delayOf(card(wall, 'b'), 'reflow-move')).toBeCloseTo(200 / 6)
    expect(delayOf(card(wall, 'c'), 'reflow-move')).toBeCloseTo(700 / 6)
    expect(delayOf(card(wall, 'd'), 'reflow-fade')).toBe(200)
    // 视口高 768，再往下 200px 以外的不做过渡。
    expect(fakes.on(card(wall, 'e'))).toHaveLength(0)
    const [move] = fakes.on(card(wall, 'a'), 'reflow-move')
    expect(move?.keyframes).toEqual([{ translate: '0px 14px' }, { translate: '0px 0px' }])
    expect(move?.options.fill).toBe('backwards')
  })

  it('换一批内容时：留下的滑到新位置，离开的在原处淡出，新来的等一拍再浮现', async () => {
    const { wrapper, wall } = mountWall(row('ABC'))
    const leaving = card(wall, 'A')
    fakes.finishAll()
    await wrapper.setProps({ wallKey: 'p2', tiles: row('BCD') })
    await flushPromises()

    const [glide] = fakes.on(card(wall, 'B'), 'reflow-glide')
    expect(glide?.keyframes).toEqual([{ translate: '200px 0px' }, { translate: '0px 0px' }])
    expect(fakes.on(card(wall, 'C'), 'reflow-glide')).toHaveLength(1)

    // 离开的卡被放回墙的底层，钉在原处，不再参与下一轮重排，也不接收点击和读屏。
    expect(leaving.isConnected).toBe(true)
    expect(leaving.hasAttribute('data-reflow-key')).toBe(false)
    expect(leaving.getAttribute('aria-hidden')).toBe('true')
    expect(leaving.style).toMatchObject({ position: 'absolute', left: '0px', top: '0px', width: '200px', height: '100px', zIndex: '-1', pointerEvents: 'none' })
    const [out] = fakes.on(leaving, 'reflow-leave')
    out!.finish()
    expect(leaving.isConnected).toBe(false)

    expect(delayOf(card(wall, 'D'), 'reflow-fade')).toBeCloseTo(120 + 400 / 6)
  })

  it('整批换掉（翻页）时旧卡直接撤下不留重影，新卡从翻去的一侧进来', async () => {
    const wrapper = mount(Wall, { props: { tiles: row('ABC'), wallKey: 'p1', from: { x: 40, y: 0 } }, attachTo: document.body })
    const wall = wrapper.element as HTMLElement
    const old = card(wall, 'A')
    await wrapper.setProps({ wallKey: 'p2', tiles: row('XY') })
    await flushPromises()
    expect(old.isConnected).toBe(false)
    expect(wall.querySelectorAll('article')).toHaveLength(2)
    expect(delayOf(card(wall, 'X'), 'reflow-move')).toBe(0)
    expect(fakes.on(card(wall, 'Y'), 'reflow-move')[0]?.keyframes).toEqual([{ translate: '40px 0px' }, { translate: '0px 0px' }])
  })

  it('key 不变的重渲染不播任何过渡', async () => {
    const { wrapper } = mountWall(row('AB'))
    const before = fakes.all.length
    await wrapper.setProps({ tiles: row('BA') })
    await flushPromises()
    expect(fakes.all).toHaveLength(before)
  })

  it('滑到一半又重排时停掉旧的滑动，从此刻起接着滑；上下都在视口外的不滑', async () => {
    const { wrapper, wall } = mountWall([...row('ABC'), { key: 'F', x: 0, y: 2000 }])
    await wrapper.setProps({ wallKey: 'p2', tiles: [...row('BC'), { key: 'F', x: 200, y: 2000 }] })
    await flushPromises()
    const [first] = fakes.on(card(wall, 'B'), 'reflow-glide')
    expect(fakes.on(card(wall, 'F'), 'reflow-glide')).toHaveLength(0)

    await wrapper.setProps({ wallKey: 'p3', tiles: [{ key: 'B', x: 0, y: 100 }, { key: 'C', x: 200, y: 0 }] })
    await flushPromises()
    expect(first?.playState).toBe('idle')
    const glides = fakes.on(card(wall, 'B'), 'reflow-glide')
    expect(glides).toHaveLength(2)
    expect(glides[1]?.keyframes).toEqual([{ translate: '0px -100px' }, { translate: '0px 0px' }])
  })

  it('用户偏好减少动态时直接换，不留离场的卡', async () => {
    stubReducedMotion()
    const { wrapper, wall } = mountWall(row('ABC'))
    const leaving = card(wall, 'A')
    await wrapper.setProps({ wallKey: 'p2', tiles: row('BCD') })
    await flushPromises()
    expect(fakes.all).toHaveLength(0)
    expect(leaving.isConnected).toBe(false)
  })
})
