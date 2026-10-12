import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { loadTemplate, type UiTemplate, type UiTemplateSummary } from './catalog'
import UiTemplateCard from './UiTemplateCard.vue'

const account = vi.hoisted(() => ({
  isAdmin: { value: false }, requireAccount: vi.fn(), copyValue: vi.fn(),
}))
vi.mock('./useUiLibraryAccount', () => ({ useUiLibraryAccount: () => account }))
vi.mock('./useViewportPreview', async () => {
  const { ref } = await import('vue')
  return { useViewportPreview: () => ({ attached: ref(false), playing: ref(false) }) }
})
const seed: UiTemplate = JSON.parse(readFileSync(resolve('../mcp-go/internal/uicatalog/data/catalog.json'), 'utf8')).items[0]
const full: UiTemplate = {
  ...seed, id: 'demo:card',
  files: [
    { name: 'first.html', path: 'sources/first.html', sha256: 'a'.repeat(64) },
    { name: 'second.css', path: 'sources/second.css', sha256: 'b'.repeat(64) },
  ],
  notices: [{ name: 'LICENSE', path: 'licenses/demo/LICENSE', sha256: 'c'.repeat(64) }],
}
const summary: UiTemplateSummary = { ...full, files: full.files.slice(0, 1) }
const stubs = { UiLikeButton: true, UiDeprecationButton: true, UiCardVideo: true }

beforeEach(() => {
  account.requireAccount.mockReset().mockResolvedValue(true)
  account.copyValue.mockReset().mockResolvedValue(true)
  vi.stubGlobal('fetch', vi.fn(async (url: string) => ({
    ok: true,
    json: async () => ({ version: 1, items: [full] }),
    text: async () => `contents of ${url}`,
  })))
})
afterEach(() => vi.unstubAllGlobals())

describe('summary cards and on-demand source metadata', () => {
  it.each(['source', 'prompt'] as const)('loads every source and notice only when copying %s', async kind => {
    const wrapper = mount(UiTemplateCard, { props: { item: summary, lang: 'zh', previewEnabled: false }, global: { stubs } })
    expect(fetch).not.toHaveBeenCalled()
    await wrapper.get(`.ui-library__copy-${kind}`).trigger('click')
    await flushPromises()
    expect(fetch).toHaveBeenCalledWith('/api/ui-library/catalog?template_id=demo%3Acard', expect.objectContaining({ cache: 'no-store' }))
    const copied = account.copyValue.mock.calls[0]![2]
    expect(copied).toContain('contents of /ui-library/sources/first.html')
    expect(copied).toContain('contents of /ui-library/sources/second.css')
    expect(copied).toContain('contents of /ui-library/licenses/demo/LICENSE')
    if (kind === 'prompt') {
      expect(copied).toContain(full.license)
      expect(copied).toContain(full.source_url)
    }
    wrapper.unmount()
  })

  it('does not copy partial data when the material has been removed or hidden', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => ({ version: 1, items: [] }) })))
    const wrapper = mount(UiTemplateCard, { props: { item: summary, lang: 'zh', previewEnabled: false }, global: { stubs } })
    await wrapper.get('.ui-library__copy-source').trigger('click')
    await flushPromises()
    expect(account.copyValue).not.toHaveBeenCalled()
    expect(wrapper.find('[role="status"]').exists()).toBe(true)
    wrapper.unmount()
    await expect(loadTemplate(full.id)).rejects.toThrow('Source unavailable')
  })

  it('cancels a pending detail request when navigating away', async () => {
    let complete!: (value: unknown) => void
    const fetcher = vi.fn(() => new Promise(done => { complete = done }))
    vi.stubGlobal('fetch', fetcher)
    const wrapper = mount(UiTemplateCard, { props: { item: summary, lang: 'zh', previewEnabled: false }, global: { stubs } })
    await wrapper.get('.ui-library__copy-source').trigger('click')
    await flushPromises()
    const signal = vi.mocked(fetch).mock.calls[0]![1]!.signal!
    wrapper.unmount()
    expect(signal.aborted).toBe(true)
    complete({ ok: true, json: async () => ({ version: 1, items: [full] }) })
    await flushPromises()
    expect(fetcher).toHaveBeenCalledOnce()
    expect(account.copyValue).not.toHaveBeenCalled()
  })
})
