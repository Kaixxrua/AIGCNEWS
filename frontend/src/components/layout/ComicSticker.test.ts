import { mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { nextTick } from 'vue'
import ComicSticker from './ComicSticker.vue'

type Resize = (entries: { contentRect: { width: number; height: number } }[]) => void

const observers: StubResizeObserver[] = []
class StubResizeObserver {
  disconnect = vi.fn()
  callback: Resize
  constructor(callback: Resize) {
    this.callback = callback
    observers.push(this)
  }
  observe() {}
}

const resize = async (width: number, height = 92) => {
  observers[observers.length - 1]?.callback([{ contentRect: { width, height } }])
  await nextTick()
}

afterEach(() => {
  observers.length = 0
  vi.unstubAllGlobals()
})

describe('ComicSticker', () => {
  it.each(['corner', 'shout', 'peel'] as const)('keeps the %s sticker out of the accessibility tree', variant => {
    const wrapper = mount(ComicSticker, { props: { variant, text: 'Create freely!' } })
    expect(wrapper.attributes('aria-hidden')).toBe('true')
    expect(wrapper.classes()).toContain(`comic-sticker--${variant}`)
  })

  it('shouts from the masthead corner', () => {
    const wrapper = mount(ComicSticker, { props: { variant: 'corner' } })
    expect(new Set(wrapper.findAll('text').map(t => t.text()))).toEqual(new Set(['AI!', 'BRIGHTER TOMORROW!']))
    expect(wrapper.find('image').exists()).toBe(false)
  })

  it('lets a fixed-size robot out of the footer tear so it cannot shift layout', () => {
    const wrapper = mount(ComicSticker, { props: { variant: 'peel' } })
    const image = wrapper.get('image')
    expect(image.attributes('href')).toBe('/assets/comic/sticker-robot-burst.webp')
    expect(image.attributes('width')).toBeTruthy()
    expect(image.attributes('height')).toBeTruthy()
    // The robot is clipped to the torn hole, never drawn over the page around it.
    expect(image.element.parentElement?.getAttribute('clip-path')).toMatch(/^url\(#comic-.+-hole\)$/)
    expect(wrapper.findAll('text').map(t => t.text())).toEqual(['MORE', 'CREATORS!', 'A BRIGHTER WORLD'])
  })

  it('tears the shout only once it knows its width', async () => {
    vi.stubGlobal('ResizeObserver', StubResizeObserver)
    const wrapper = mount(ComicSticker, { props: { variant: 'shout', text: '让创造更自由！' } })
    expect(wrapper.find('svg').exists()).toBe(false)

    await resize(320)
    expect(wrapper.classes()).toContain('comic-sticker--full')
    expect(wrapper.get('svg').attributes('viewBox')).toBe('0 0 320 92')
    expect(new Set(wrapper.findAll('text').map(t => t.text()))).toEqual(new Set(['让创造更自由！']))

    await resize(180)
    expect(wrapper.classes()).toContain('comic-sticker--compact')

    await resize(140)
    expect(wrapper.find('svg').exists()).toBe(false)
  })

  it('renders nothing for the shout where ResizeObserver is missing', () => {
    vi.stubGlobal('ResizeObserver', undefined)
    const wrapper = mount(ComicSticker, { props: { variant: 'shout', text: 'Create freely!' } })
    expect(wrapper.find('svg').exists()).toBe(false)
  })

  it('stops observing when unmounted', () => {
    vi.stubGlobal('ResizeObserver', StubResizeObserver)
    const wrapper = mount(ComicSticker, { props: { variant: 'shout', text: 'Create freely!' } })
    wrapper.unmount()
    expect(observers[0]?.disconnect).toHaveBeenCalled()
  })
})
