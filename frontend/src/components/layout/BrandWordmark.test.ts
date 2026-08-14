import { createApp, nextTick } from 'vue'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import BrandWordmark from './BrandWordmark.vue'

let unmount: (() => void) | undefined
const originalMatchMedia = window.matchMedia

const stubMatchMedia = (reduced: boolean) => {
  window.matchMedia = ((query: string) => ({
    matches: reduced && query === '(prefers-reduced-motion: reduce)',
    media: query,
    onchange: null,
    addListener: () => undefined,
    removeListener: () => undefined,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
    dispatchEvent: () => false,
  })) as typeof window.matchMedia
}

const mountWordmark = (text = 'AIGC NEWS') => {
  const host = document.createElement('div')
  document.body.appendChild(host)
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/', component: { template: '<div />' } }],
  })
  const app = createApp(BrandWordmark, { text })
  app.use(router)
  app.mount(host)
  unmount = () => {
    app.unmount()
    host.remove()
  }
  return host
}

describe('BrandWordmark', () => {
  beforeEach(() => {
    stubMatchMedia(false)
  })

  afterEach(() => {
    unmount?.()
    unmount = undefined
    window.matchMedia = originalMatchMedia
    vi.restoreAllMocks()
    vi.useRealTimers()
  })

  it('renders the brand text as per-character spans inside a home link', async () => {
    const host = mountWordmark()
    await nextTick()
    await nextTick()

    const link = host.querySelector('a.brand-wordmark') as HTMLAnchorElement
    expect(link.getAttribute('href')).toBe('/')
    expect(link.getAttribute('aria-label')).toBe('AIGC NEWS')

    const chars = host.querySelectorAll('.brand-wordmark__char')
    expect(chars).toHaveLength('AIGC NEWS'.length)
    const text = host.querySelector('.brand-wordmark__text') as HTMLElement
    expect(text.querySelector('.bw-fringe--cyan')?.textContent).toBe('AIGC NEWS')
    expect(text.querySelector('.bw-slice--magenta')?.textContent).toBe('AIGC NEWS')
    expect(text.textContent).toContain('AIGC NEWS')
  })

  it('scrambles characters to glyphs and restores them', async () => {
    vi.useFakeTimers()
    const host = mountWordmark()
    await nextTick()
    await nextTick()
    const text = host.querySelector('.brand-wordmark__text') as HTMLElement
    // 残影层持有原文拷贝，断言只针对字符 span
    const charText = () =>
      [...text.querySelectorAll('.brand-wordmark__char')].map((el) => el.textContent).join('')

    // random→0：每个非空字符立即扰动，字形恒为字形池首字符 ▓
    // （首帧只标记扰动，次帧才替换字形，故推进跨过两个 tick）
    vi.spyOn(Math, 'random').mockReturnValue(0)
    vi.advanceTimersByTime(250)
    await nextTick()
    expect(charText()).toBe('AIGC NEWS'.replace(/[^ ]/g, '▓'))

    // random→0.9999：不再触发新扰动，存量扰动在数帧内全部还原
    vi.spyOn(Math, 'random').mockReturnValue(0.9999)
    vi.advanceTimersByTime(600)
    await nextTick()
    expect(charText()).toBe('AIGC NEWS')
  })

  it('stays static when reduced motion is preferred', async () => {
    stubMatchMedia(true)
    vi.useFakeTimers()
    const host = mountWordmark()
    await nextTick()
    await nextTick()
    const text = host.querySelector('.brand-wordmark__text') as HTMLElement
    const charText = () =>
      [...text.querySelectorAll('.brand-wordmark__char')].map((el) => el.textContent).join('')

    vi.spyOn(Math, 'random').mockReturnValue(0)
    vi.advanceTimersByTime(2000)
    await nextTick()
    expect(charText()).toBe('AIGC NEWS')
  })
})
