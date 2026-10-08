import { enableAutoUnmount, mount } from '@vue/test-utils'
import { computed, h, KeepAlive, nextTick, ref } from 'vue'
import { createI18n } from 'vue-i18n'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useDocumentVisibility, useElementVisibility, usePreferredReducedMotion } from '@vueuse/core'
import type { UiTemplate } from '@/features/ui-library/catalog'
import DashboardUiShowcase from './DashboardUiShowcase.vue'

vi.mock('@vueuse/core', async original => ({
  ...await original<typeof import('@vueuse/core')>(),
  useElementVisibility: vi.fn(),
  useDocumentVisibility: vi.fn(),
  usePreferredReducedMotion: vi.fn(),
}))

enableAutoUnmount(afterEach)
const visible = ref(true)
const visibility = ref<DocumentVisibilityState>('visible')
const motion = ref<'reduce' | 'no-preference'>('no-preference')
const template = (id: string, overrides = {}) => ({ id, clip_url: `/clips/${id}.mp4`, poster_url: `/posters/${id}.webp`, ...overrides }) as UiTemplate
const first = template('eui-shader-worlds')
const second = template('threeui-liquidformbackground')
const third = template('eui-fluid-studio')
const plugins = () => [
  createI18n({ legacy: false, locale: 'zh', messages: { zh: { dashboard: { editorial: { inspiration: 'UI 灵感库', explore: '探索更多' } } } } }),
  createRouter({ history: createMemoryHistory(), routes: [
    { path: '/', component: { template: '<div />' } },
    { path: '/ui-library/:id?', name: 'ui-library', component: { template: '<div />' } },
  ] }),
]
function showcase(items = [first, second, third]) {
  return mount(DashboardUiShowcase, {
    props: { items },
    global: { plugins: plugins() },
  })
}

describe('homepage UI showcase', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.spyOn(Math, 'random').mockReturnValue(0)
    localStorage.clear()
    visible.value = true
    visibility.value = 'visible'
    motion.value = 'no-preference'
    vi.mocked(useElementVisibility).mockReturnValue(visible)
    vi.mocked(useDocumentVisibility).mockReturnValue(visibility)
    vi.mocked(usePreferredReducedMotion).mockReturnValue(computed(() => motion.value))
  })
  afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks() })

  it('shows only curated works with both media assets, in the chosen order', () => {
    const wrapper = showcase([template('ordinary-checkbox'), second, template(third.id, { clip_url: '' }), first])
    expect(wrapper.get('.ui-inspiration__position').text()).toBe('01/ 02')
    expect(wrapper.get('.ui-inspiration__art').attributes('href')).toBe(`/ui-library/${first.id}`)
    expect(wrapper.get('video').attributes('src')).toBe(first.clip_url)
    expect(wrapper.get('.ui-inspiration__caption').text()).toContain('黑洞视界')
    expect(wrapper.get('.ui-inspiration__heading').attributes('href')).toBe('/ui-library')
  })

  it('keeps the entry selection until manually changed and keeps its title, media and destination together', async () => {
    const wrapper = showcase([first, second])
    await vi.advanceTimersByTimeAsync(60000)
    expect(wrapper.get('video').attributes('src')).toBe(first.clip_url)
    await wrapper.get('button[aria-label="下一个模板"]').trigger('click')
    expect(wrapper.get('video').attributes('src')).toBe(second.clip_url)
    expect(wrapper.get('.ui-inspiration__art').attributes('href')).toBe(`/ui-library/${second.id}`)
    expect(wrapper.get('.ui-inspiration__caption').text()).toContain('液态金属')
    await wrapper.get('button[aria-label="下一个模板"]').trigger('click')
    expect(wrapper.get('video').attributes('src')).toBe(first.clip_url)
    await wrapper.get('button[aria-label="上一个模板"]').trigger('click')
    expect(wrapper.get('video').attributes('src')).toBe(second.clip_url)
  })

  it('randomly selects a template on entry and avoids the previous selection after a reload', () => {
    vi.mocked(Math.random).mockReturnValue(0.75)
    const initial = showcase()
    expect(initial.get('video').attributes('src')).toBe(third.clip_url)
    expect(initial.get('.ui-inspiration__art').attributes('href')).toBe(`/ui-library/${third.id}`)
    initial.unmount()
    const reloaded = showcase()
    expect(reloaded.get('video').attributes('src')).toBe(second.clip_url)
  })

  it('selects again when returning to the cached homepage, without selecting twice on initial mount', async () => {
    const home = ref(true)
    const wrapper = mount(() => h(KeepAlive, null, {
      default: () => home.value ? h(DashboardUiShowcase, { items: [first, second, third] }) : h('div'),
    }), { global: { plugins: plugins() } })
    expect(wrapper.get('video').attributes('src')).toBe(first.clip_url)
    const original = wrapper.get('.ui-inspiration').element
    home.value = false
    await nextTick()
    home.value = true
    await nextTick()
    expect(wrapper.get('.ui-inspiration').element).toBe(original)
    expect(wrapper.get('video').attributes('src')).toBe(second.clip_url)
  })

  it('lets visitors pause motion and manually choose another template', async () => {
    const wrapper = showcase()
    await wrapper.get('button[aria-label="暂停动效"]').trigger('click')
    await vi.advanceTimersByTimeAsync(16000)
    expect(wrapper.find('video').exists()).toBe(false)
    expect(wrapper.get('img').attributes('src')).toBe(first.poster_url)
    await wrapper.get('button[aria-label="下一个模板"]').trigger('click')
    expect(wrapper.get('img').attributes('src')).toBe(second.poster_url)
    await wrapper.get('button[aria-label="播放动效"]').trigger('click')
    await vi.advanceTimersByTimeAsync(8000)
    expect(wrapper.get('video').attributes('src')).toBe(second.clip_url)
  })

  it.each(['viewport', 'document', 'reduced motion'])('stops automatic media for %s without changing the selection', async reason => {
    const wrapper = showcase()
    if (reason === 'viewport') visible.value = false
    if (reason === 'document') visibility.value = 'hidden'
    if (reason === 'reduced motion') motion.value = 'reduce'
    await nextTick()
    await vi.advanceTimersByTimeAsync(16000)
    expect(wrapper.find('video').exists()).toBe(false)
    expect(wrapper.get('img').attributes('src')).toBe(first.poster_url)
    if (reason === 'reduced motion') {
      expect(wrapper.find('button[aria-label="播放动效"]').exists()).toBe(false)
      await wrapper.get('button[aria-label="下一个模板"]').trigger('click')
      expect(wrapper.get('img').attributes('src')).toBe(second.poster_url)
    }
  })

  it('falls back to a poster on clip failure, skips a broken poster, and keeps other previews playable', async () => {
    const wrapper = showcase([first, second])
    await wrapper.get('video').trigger('error')
    expect(wrapper.get('img').attributes('src')).toBe(first.poster_url)
    await wrapper.get('img').trigger('error')
    expect(wrapper.get('video').attributes('src')).toBe(second.clip_url)
    expect(wrapper.get('.ui-inspiration__art').attributes('href')).toBe(`/ui-library/${second.id}`)
    await wrapper.get('video').trigger('error')
    await wrapper.get('img').trigger('error')
    expect(wrapper.find('.ui-inspiration__fallback').exists()).toBe(true)
    expect(wrapper.get('.ui-inspiration__art').attributes('href')).toBe('/ui-library')
    expect(wrapper.find('button').exists()).toBe(false)
  })

  it('waits for the catalog, then preserves the random selection across catalog refreshes', async () => {
    vi.mocked(Math.random).mockReturnValue(0.75)
    const wrapper = showcase([])
    expect(wrapper.find('.ui-inspiration__fallback').exists()).toBe(true)
    await wrapper.setProps({ items: [first, second] })
    expect(wrapper.get('video').attributes('src')).toBe(second.clip_url)
    await wrapper.setProps({ items: [first, second, third] })
    expect(wrapper.get('video').attributes('src')).toBe(second.clip_url)
  })

  it('still displays a lone available template on repeated visits', () => {
    const initial = showcase([first])
    initial.unmount()
    expect(showcase([first]).get('video').attributes('src')).toBe(first.clip_url)
  })

  it('still chooses a template when browser storage is blocked', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('blocked') })
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('blocked') })
    vi.mocked(Math.random).mockReturnValue(0.75)
    expect(showcase().get('video').attributes('src')).toBe(third.clip_url)
  })
})
