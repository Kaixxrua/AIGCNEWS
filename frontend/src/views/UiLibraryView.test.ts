import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent } from 'vue'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { i18n } from '@/i18n'
import type { UiTemplate } from '@/features/ui-library/catalog'
import { __resetPageHeadForTest, installPageHead } from '@/seo/pageHead'
import UiLibraryView from './UiLibraryView.vue'

const mocks = vi.hoisted(() => ({ get: vi.fn(), isAdmin: { value: false } }))
vi.mock('@/services/http/apiClient', () => ({ api: { get: mocks.get } }))
vi.mock('@/features/ui-library/useUiLibraryAccount', async () => {
  const { ref } = await import('vue')
  mocks.isAdmin = ref(false)
  return {
    provideUiLibraryAccount: () => ({ isAdmin: mocks.isAdmin, stats: ref({}), loadError: ref(false), quotaText: ref(''), refresh: async () => undefined }),
  }
})

const template: UiTemplate = {
  id: 'demo:glass-button',
  kind: 'component',
  name: { zh: '玻璃按钮', en: 'Glass Button' },
  description: { zh: '一枚半透明的按钮。', en: 'A translucent button.' },
  notes: { zh: '', en: '' },
  provider: 'Demo',
  provider_id: 'demo',
  author: 'someone',
  license: 'MIT',
  license_url: '',
  revision: '1',
  source_url: '',
  demo_url: '',
  category: 'button',
  frameworks: ['html'],
  aliases: [],
  files: [],
  notices: [],
  dependencies: {},
  export_name: 'GlassButton',
  props: {},
  assets: [],
  preview_url: '',
  clip_url: '',
  poster_url: '',
}

const stubs = { UiTemplateDialog: true, UiTemplateCard: true, UiIconCard: true, UiIconDialog: true, UiMcpRecommendation: true }
let stopHead: (() => void) | null = null

async function openLibraryAt(path: string) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/ui-library/:id?', name: 'ui-library', component: UiLibraryView },
      { path: '/mcp', name: 'mcp-connect', component: defineComponent({ render: () => null }) },
    ],
  })
  await router.push(path)
  stopHead = installPageHead(router, document)
  const wrapper = mount(UiLibraryView, { global: { plugins: [router, i18n], stubs } })
  await flushPromises()
  return wrapper
}

beforeEach(() => {
  mocks.isAdmin.value = false
  mocks.get.mockReset()
  i18n.global.locale.value = 'zh-CN'
  document.head.innerHTML = ''
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => ({ version: 1, items: [template], icon_count: 0 }) })))
})

afterEach(() => {
  stopHead?.()
  stopHead = null
  __resetPageHeadForTest()
  vi.unstubAllGlobals()
})

describe('UiLibraryView item address', () => {
  it('renders cards in small batches while searching the complete catalog', async () => {
    const rows = Array.from({ length: 80 }, (_, id) => ({
      ...template, id: String(id), name: { zh: `按钮${id}`, en: `Button ${id}` },
    }))
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => ({ version: 1, items: rows }) })))
    const wrapper = await openLibraryAt('/ui-library')
    expect(wrapper.findAll('ui-template-card-stub')).toHaveLength(32)
    await wrapper.get('.ui-library__load-more button').trigger('click')
    expect(wrapper.findAll('ui-template-card-stub')).toHaveLength(64)
    await wrapper.get('input[type="search"]').setValue('按钮79')
    await flushPromises()
    expect(wrapper.findAll('ui-template-card-stub')).toHaveLength(1)
    expect(wrapper.findComponent({ name: 'UiTemplateCard' }).props('item').id).toBe('79')
    wrapper.unmount()
  })

  it('lets admins restore deprecated items and closes their detail when admin access ends', async () => {
    mocks.isAdmin.value = true
    mocks.get.mockResolvedValue({ data: { version: 1, items: [{ ...template, deprecated: true }], icon_count: 0 } })
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => ({ version: 1, items: [], icon_count: 0 }) })))
    const wrapper = await openLibraryAt('/ui-library/demo:glass-button')
    expect(mocks.get).toHaveBeenCalledWith('/ui-library/catalog', expect.objectContaining({ params: { summary: 'true', include_deprecated: true } }))
    expect(wrapper.find('ui-template-dialog-stub').exists()).toBe(true)
    expect(wrapper.findComponent({ name: 'UiTemplateCard' }).props('item').deprecated).toBe(true)
    mocks.isAdmin.value = false
    await flushPromises()
    expect(wrapper.find('ui-template-dialog-stub').exists()).toBe(false)
    expect(wrapper.find('ui-template-card-stub').exists()).toBe(false)
    expect(wrapper.find('.ui-library__not-found').exists()).toBe(true)
    expect(document.head.querySelector('meta[name="robots"]')?.getAttribute('content')).toBe('noindex')
    expect(fetch).toHaveBeenCalledWith('/api/ui-library/catalog?summary=true', expect.objectContaining({ cache: 'no-store' }))
    wrapper.unmount()
  })

  it('does not restore an admin catalog from a late response after logout', async () => {
    mocks.isAdmin.value = true
    let resolve!: (value: unknown) => void
    mocks.get.mockReturnValue(new Promise(done => { resolve = done }))
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => ({ version: 1, items: [], icon_count: 0 }) })))
    const wrapper = await openLibraryAt('/ui-library/demo:glass-button')
    mocks.isAdmin.value = false
    await flushPromises()
    resolve({ data: { version: 1, items: [{ ...template, deprecated: true }], icon_count: 0 } })
    await flushPromises()
    expect(wrapper.find('ui-template-card-stub').exists()).toBe(false)
    expect(wrapper.find('ui-template-dialog-stub').exists()).toBe(false)
    expect(wrapper.find('.ui-library__not-found').exists()).toBe(true)
    wrapper.unmount()
  })

  it('opens a known item without the not-found notice and titles the page after it', async () => {
    const wrapper = await openLibraryAt('/ui-library/demo:glass-button')
    expect(wrapper.find('ui-template-dialog-stub').exists()).toBe(true)
    expect(wrapper.find('.ui-library__not-found').exists()).toBe(false)
    expect(document.title).toBe('玻璃按钮 · AIGCNEWS')
    expect(document.head.querySelector('meta[name="description"]')?.getAttribute('content')).toBe('一枚半透明的按钮。')
    expect(document.head.querySelector('meta[name="robots"]')).toBeNull()
    expect(document.head.querySelector('link[rel="canonical"]')?.getAttribute('href')).toBe('https://aigcnews.cn/ui-library/demo:glass-button')
    wrapper.unmount()
  })

  it('says an unknown item is not there and keeps that address out of search results', async () => {
    const wrapper = await openLibraryAt('/ui-library/demo:gone')
    expect(wrapper.find('ui-template-dialog-stub').exists()).toBe(false)
    expect(wrapper.find('.ui-library__not-found').exists()).toBe(true)
    expect(document.title).toBe('UI 灵感库 · AIGCNEWS')
    expect(document.head.querySelector('meta[name="robots"]')?.getAttribute('content')).toBe('noindex')
    expect(document.head.querySelector('link[rel="canonical"]')).toBeNull()
    wrapper.unmount()
  })

  it('does not call the item missing while the catalog failed to load', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, json: async () => ({}) })))
    const wrapper = await openLibraryAt('/ui-library/demo:glass-button')
    expect(wrapper.find('.ui-library__not-found').exists()).toBe(false)
    expect(document.head.querySelector('meta[name="robots"]')).toBeNull()
    wrapper.unmount()
  })
})
