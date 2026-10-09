import { afterEach, describe, expect, it, vi } from 'vitest'
import { loadUiShowcaseCatalog, selectUiShowcase } from './uiShowcase'

afterEach(() => vi.unstubAllGlobals())

describe('homepage UI catalog', () => {
  it('selects only usable curated previews in editorial order', () => {
    const items = [
      { id: 'ordinary-control', poster_url: '/ordinary.webp', clip_url: '/ordinary.mp4' },
      { id: 'eui-fluid-studio', poster_url: '/fluid.webp', clip_url: '' },
      { id: 'eui-rainy-notes', poster_url: '/rain.webp', clip_url: '/rain.mp4' },
      { id: 'eui-shader-worlds', poster_url: '/shader.webp', clip_url: '/shader.mp4' },
    ]
    const selected = selectUiShowcase(items)
    expect(selected.map(({ id }) => id)).toEqual(['eui-shader-worlds', 'eui-rainy-notes'])
    expect(selected[0]?.name.zh).toBe('黑洞视界')
  })

  it('loads only the live summary without caching and forwards cancellation', async () => {
    const payload = { version: 1, total: 240, items: [] }
    const fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => payload })
    vi.stubGlobal('fetch', fetch)
    const signal = new AbortController().signal
    expect(await loadUiShowcaseCatalog(signal)).toEqual(payload)
    expect(fetch).toHaveBeenCalledTimes(1)
    const [path, options] = fetch.mock.calls[0]!
    const url = new URL(path, 'https://example.com')
    expect(url.pathname).toBe('/api/ui-library/dashboard')
    expect(url.searchParams.getAll('ids')).toEqual([
      'eui-shader-worlds', 'threeui-liquidformbackground', 'eui-fluid-studio', 'eui-adventure-roadbook',
      'eui-bigscreen-cockpit', 'kokonut-flow-field', 'eui-exploded-view', 'eui-rainy-notes',
    ])
    expect(options).toEqual({ signal, cache: 'no-store' })
  })

  it('does not fall back to an unfiltered static catalog on failure', async () => {
    const fetch = vi.fn().mockResolvedValue({ ok: false, status: 503 })
    vi.stubGlobal('fetch', fetch)
    await expect(loadUiShowcaseCatalog()).rejects.toThrow('Dashboard catalog unavailable')
    expect(fetch).toHaveBeenCalledTimes(1)
  })

  it.each([
    { version: 1, items: [] },
    { version: 1, total: -1, items: [] },
    { version: 1, total: 1, items: [null] },
    { version: 1, total: 1, items: [{ id: 'broken' }] },
    { version: 2, total: 1, items: [] },
  ])('keeps invalid counts and media out of the dashboard: %j', async payload => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => payload }))
    await expect(loadUiShowcaseCatalog()).rejects.toThrow('Invalid dashboard catalog')
  })
})
