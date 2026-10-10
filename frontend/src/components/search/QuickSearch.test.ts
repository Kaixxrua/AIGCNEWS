import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { nextTick } from 'vue'
import { createI18n } from 'vue-i18n'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import enUS from '@/i18n/locales/en-US'
import { useQuickSearch } from '@/composables/useQuickSearch'
import { QUICK_SEARCH_DEBOUNCE_MS, RECENT_QUERIES_KEY } from '@/features/search/quickSearch'
import type { UiTemplate } from '@/features/ui-library/catalog'
import type { QuickSearchResult } from '@/services/search/searchApi'
import QuickSearch from './QuickSearch.vue'

const auth = vi.hoisted(() => ({ state: null as any, requestLogin: vi.fn() }))
vi.mock('@/stores/authStore', async () => {
  const { reactive } = await import('vue')
  auth.state = reactive({ isLoggedIn: true, ensureInitialized: vi.fn(async () => {}) })
  return { useAuthStore: () => auth.state }
})
vi.mock('@/composables/useLoginPrompt', () => ({ useLoginPrompt: () => ({ requestLogin: auth.requestLogin }) }))

const search = vi.hoisted(() => ({ fetch: vi.fn() }))
vi.mock('@/services/search/searchApi', async importOriginal => ({
  ...await importOriginal<typeof import('@/services/search/searchApi')>(),
  fetchQuickSearch: search.fetch,
}))

const catalog = vi.hoisted(() => ({ load: vi.fn() }))
vi.mock('@/features/ui-library/catalog', async importOriginal => ({
  ...await importOriginal<typeof import('@/features/ui-library/catalog')>(),
  loadCatalog: catalog.load,
}))

const i18n = createI18n({ legacy: false, locale: 'en-US', messages: { 'en-US': enUS } })

const view = { template: '<div />' }
const makeRouter = () => createRouter({
  history: createMemoryHistory(),
  routes: [
    { path: '/', name: 'dashboard', component: view },
    { path: '/projects', name: 'github-projects', component: view },
    { path: '/papers/:id/read', name: 'paper-read', component: view },
    { path: '/report', name: 'report', component: view },
    { path: '/ui-library/:id?', name: 'ui-library', component: view },
  ],
})

const RESULT: QuickSearchResult = {
  q: 'agent',
  projects: { total: 1, items: [{ fullName: 'acme/agent', url: 'https://github.com/acme/agent', description: 'An agent', descriptionZh: '', descriptionEn: 'An agent', stars: 1200, language: 'Python' }] },
  papers: { total: 1, items: [{ id: '2410.00001', title: 'Agents at scale', summary: 'We study agents.', date: '2026-09-30', authors: ['Ada'], authorCount: 1 }] },
  briefings: { total: 1, items: [{ date: '2026-09-30', type: 'github', title: 'GitHub', lead: 'acme/agent tops the chart', snippet: '…agent…' }] },
  tweets: { total: 1, items: [{ id: 't1', text: 'agents are here', url: 'https://x.com/ada/status/1', author: 'ada', date: '2026-09-30' }] },
  failed: [],
}

const TEMPLATE = {
  id: 'agent-card',
  name: { zh: '智能体卡片', en: 'Agent card' },
  description: { zh: '给智能体用的卡片', en: 'A card for agents' },
  provider: 'Uiverse',
  aliases: [],
  frameworks: ['html'],
  category: 'cards',
} as unknown as UiTemplate

let wrapper: VueWrapper | null = null

async function mountSearch(enabled = true) {
  const router = makeRouter()
  await router.push('/')
  await router.isReady()
  wrapper = mount(QuickSearch, {
    props: { enabled },
    attachTo: document.body,
    global: { plugins: [router, i18n], stubs: { teleport: true } },
  })
  return { router, wrapper }
}

const press = (init: KeyboardEventInit) => {
  const event = new KeyboardEvent('keydown', { bubbles: true, cancelable: true, ...init })
  window.dispatchEvent(event)
  return event
}

/** 等防抖过去、请求落地。 */
const settle = async () => {
  await new Promise(resolve => setTimeout(resolve, QUICK_SEARCH_DEBOUNCE_MS + 30))
  await flushPromises()
}

async function openWith(text: string) {
  useQuickSearch().show()
  await flushPromises()
  const input = wrapper!.find('input')
  await input.setValue(text)
  await settle()
  return input
}

const dialog = () => wrapper!.find('[role="dialog"]')
const options = () => wrapper!.findAll('[role="option"]')
const heads = () => wrapper!.findAll('.quick-search__head').map(head => head.findAll('span')[0]?.text())

beforeAll(() => {
  // jsdom 没有 scrollIntoView。
  Element.prototype.scrollIntoView = vi.fn()
})

beforeEach(() => {
  auth.state.isLoggedIn = true
  auth.state.ensureInitialized.mockReset().mockResolvedValue(undefined)
  auth.requestLogin.mockReset()
  search.fetch.mockReset()
  catalog.load.mockReset()
  catalog.load.mockResolvedValue([TEMPLATE])
  localStorage.clear()
})

afterEach(() => {
  useQuickSearch().hide()
  wrapper?.unmount()
  wrapper = null
  vi.restoreAllMocks()
})

describe('QuickSearch', () => {
  it('opens on Ctrl+K only on desktop and closes on Escape, handing focus back', async () => {
    await mountSearch(false)
    const opener = document.createElement('button')
    document.body.append(opener)
    opener.focus()

    expect(press({ key: 'k', ctrlKey: true }).defaultPrevented).toBe(false)
    await nextTick()
    expect(dialog().exists()).toBe(false)

    await wrapper!.setProps({ enabled: true })
    expect(press({ key: 'k', ctrlKey: true }).defaultPrevented).toBe(true)
    await flushPromises()
    expect(dialog().attributes('aria-modal')).toBe('true')
    expect(document.activeElement).toBe(wrapper!.find('input').element)

    await wrapper!.find('input').trigger('keydown', { key: 'Escape' })
    expect(dialog().exists()).toBe(false)
    expect(document.activeElement).toBe(opener)
    opener.remove()
  })

  it('focuses the box when the magnifier was clicked before the panel finished loading', async () => {
    useQuickSearch().show()
    await mountSearch()
    await flushPromises()

    expect(dialog().attributes('aria-modal')).toBe('true')
    expect(document.activeElement).toBe(wrapper!.find('input').element)
  })

  it('does not stack on top of another dialog', async () => {
    await mountSearch()
    const other = document.createElement('div')
    other.setAttribute('aria-modal', 'true')
    other.getClientRects = () => ({ length: 1 }) as unknown as DOMRectList
    document.body.append(other)

    expect(press({ key: 'k', ctrlKey: true }).defaultPrevented).toBe(false)
    await nextTick()
    expect(dialog().exists()).toBe(false)
    other.remove()
  })

  it('searches once typing pauses, groups the results and opens the picked one with Enter', async () => {
    search.fetch.mockResolvedValue(RESULT)
    const { router } = await mountSearch()
    useQuickSearch().show()
    await flushPromises()
    const input = wrapper!.find('input')
    await input.setValue('agent')
    expect(search.fetch).not.toHaveBeenCalled()
    await settle()

    expect(search.fetch).toHaveBeenCalledTimes(1)
    expect(search.fetch).toHaveBeenCalledWith('agent', expect.objectContaining({ locale: 'en-US', limit: 5 }))
    expect(heads()).toEqual(['Projects', 'Papers', 'Briefings', 'Posts on X', 'UI Library'])
    expect(options()).toHaveLength(5)
    expect(options()[0]?.attributes('aria-selected')).toBe('true')
    expect(wrapper!.findAll('mark').map(mark => mark.text())).toContain('agent')

    await input.trigger('keydown', { key: 'ArrowDown' })
    expect(options()[1]?.attributes('aria-selected')).toBe('true')
    expect(input.attributes('aria-activedescendant')).toBe(options()[1]?.attributes('id'))

    await input.trigger('keydown', { key: 'Enter' })
    await flushPromises()
    expect(router.currentRoute.value.fullPath).toBe('/papers/2410.00001/read')
    expect(dialog().exists()).toBe(false)
    expect(JSON.parse(localStorage.getItem(RECENT_QUERIES_KEY) ?? '[]')).toEqual(['agent'])
  })

  it('wraps around with the arrow keys', async () => {
    search.fetch.mockResolvedValue(RESULT)
    await mountSearch()
    const input = await openWith('agent')

    await input.trigger('keydown', { key: 'ArrowUp' })
    expect(options()[4]?.attributes('aria-selected')).toBe('true')
    await input.trigger('keydown', { key: 'ArrowDown' })
    expect(options()[0]?.attributes('aria-selected')).toBe('true')
  })

  it('keeps the last words but starts again from the first row when reopened', async () => {
    search.fetch.mockResolvedValue(RESULT)
    await mountSearch()
    const input = await openWith('agent')
    await input.trigger('keydown', { key: 'ArrowDown' })
    await input.trigger('keydown', { key: 'ArrowDown' })
    await input.trigger('keydown', { key: 'Escape' })

    useQuickSearch().show()
    await flushPromises()
    expect((wrapper!.find('input').element as HTMLInputElement).value).toBe('agent')
    expect(options()[0]?.attributes('aria-selected')).toBe('true')
    expect(search.fetch).toHaveBeenCalledTimes(1)
  })

  it('does not jump to the previous results while newer ones are on the way: Enter searches at once', async () => {
    search.fetch.mockResolvedValue(RESULT)
    const { router } = await mountSearch()
    const input = await openWith('agent')

    await input.setValue('agents')
    await input.trigger('keydown', { key: 'Enter' })
    expect(search.fetch).toHaveBeenCalledTimes(2)
    expect(search.fetch).toHaveBeenLastCalledWith('agents', expect.anything())
    expect(router.currentRoute.value.fullPath).toBe('/')
    expect(dialog().exists()).toBe(true)
  })

  it('opens a result in a new tab with Ctrl+Enter and stays open', async () => {
    search.fetch.mockResolvedValue(RESULT)
    const open = vi.spyOn(window, 'open').mockImplementation(() => null)
    const { router } = await mountSearch()
    const input = await openWith('agent')

    await input.trigger('keydown', { key: 'Enter', ctrlKey: true })
    expect(open).toHaveBeenCalledWith(router.resolve({ name: 'github-projects', query: { q: 'acme/agent' } }).href, '_blank', 'noopener')
    expect(router.currentRoute.value.fullPath).toBe('/')
    expect(dialog().exists()).toBe(true)
  })

  it('sends posts to x.com and closes', async () => {
    search.fetch.mockResolvedValue(RESULT)
    const open = vi.spyOn(window, 'open').mockImplementation(() => null)
    await mountSearch()
    const input = await openWith('agent')

    for (let step = 0; step < 3; step += 1) await input.trigger('keydown', { key: 'ArrowDown' })
    await input.trigger('keydown', { key: 'Enter' })
    expect(open).toHaveBeenCalledWith('https://x.com/ada/status/1', '_blank', 'noopener,noreferrer')
    expect(dialog().exists()).toBe(false)
  })

  it('lists recent searches while the box is empty and puts the picked one back in the box', async () => {
    localStorage.setItem(RECENT_QUERIES_KEY, JSON.stringify(['rag', 'agent']))
    search.fetch.mockResolvedValue(RESULT)
    await mountSearch()
    useQuickSearch().show()
    await flushPromises()

    expect(heads()).toEqual(['Recent searches'])
    expect(options().map(option => option.text())).toEqual(['rag', 'agent'])
    const input = wrapper!.find('input')
    await input.trigger('keydown', { key: 'ArrowDown' })
    await input.trigger('keydown', { key: 'Enter' })
    expect((input.element as HTMLInputElement).value).toBe('agent')
    await settle()
    expect(search.fetch).toHaveBeenCalledWith('agent', expect.anything())
  })

  it('says so when the site search is down and still lists the UI templates it found', async () => {
    search.fetch.mockRejectedValue(new Error('down'))
    await mountSearch()
    await openWith('agent')

    expect(wrapper!.find('.quick-search__notice').text()).toContain('only UI templates')
    expect(heads()).toEqual(['UI Library'])
  })
})


describe('QuickSearch member access', () => {
  it('prompts when a guest opens the lazily mounted panel', async () => {
    auth.state.isLoggedIn = false
    useQuickSearch().show()
    await mountSearch()
    await flushPromises()
    expect(dialog().exists()).toBe(false)
    expect(auth.requestLogin).toHaveBeenCalledWith('/?quickSearch=1')
    expect(search.fetch).not.toHaveBeenCalled()
  })

  it('waits for the saved session before deciding to prompt', async () => {
    auth.state.isLoggedIn = false
    let finish!: () => void
    auth.state.ensureInitialized.mockReturnValue(new Promise<void>(resolve => { finish = resolve }))
    useQuickSearch().show()
    await mountSearch()
    await flushPromises()
    expect(dialog().exists()).toBe(false)
    expect(auth.requestLogin).not.toHaveBeenCalled()
    auth.state.isLoggedIn = true
    finish()
    await flushPromises()
    expect(dialog().exists()).toBe(true)
    expect(auth.requestLogin).not.toHaveBeenCalled()
  })

  it('requires login before any search and reopens after the login redirect', async () => {
    auth.state.isLoggedIn = false
    const { router } = await mountSearch()
    useQuickSearch().show()
    await flushPromises()
    expect(dialog().exists()).toBe(false)
    expect(auth.requestLogin).toHaveBeenCalledWith('/?quickSearch=1')
    expect(search.fetch).not.toHaveBeenCalled()
    expect(catalog.load).not.toHaveBeenCalled()
    auth.state.isLoggedIn = true
    await router.push(auth.requestLogin.mock.calls[0]![0])
    await flushPromises()
    expect(dialog().exists()).toBe(true)
    expect(router.currentRoute.value.query.quickSearch).toBeUndefined()
  })

  it('clears results and closes when the session ends', async () => {
    search.fetch.mockResolvedValue(RESULT)
    await mountSearch()
    await openWith('agent')
    expect(options().length).toBeGreaterThan(0)
    auth.state.isLoggedIn = false
    await flushPromises()
    expect(dialog().exists()).toBe(false)
  })
})
