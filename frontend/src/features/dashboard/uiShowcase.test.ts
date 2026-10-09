import { afterEach, describe, expect, it, vi } from 'vitest'
import type { UiTemplate } from '@/features/ui-library/catalog'
import { buildUiShowcaseCatalog, loadUiShowcaseCatalog, selectUiShowcase } from './uiShowcase'

afterEach(() => vi.unstubAllGlobals())

describe('homepage UI catalog', () => {
  it('counts the full catalog but ships only usable curated media', () => {
    const items = [
      { id: 'ordinary-control', poster_url: '/ordinary.webp', clip_url: '/ordinary.mp4' },
      { id: 'eui-fluid-studio', poster_url: '/fluid.webp' },
      { id: 'eui-shader-worlds', poster_url: '/shader.webp', clip_url: '/shader.mp4', files: [{ path: 'large-source.ts' }], notes: { en: 'Not needed on the homepage' } },
    ] as UiTemplate[]
    const summary = buildUiShowcaseCatalog(items)
    expect(summary).toEqual({
      version: 1, total: 3,
      items: [{ id: 'eui-shader-worlds', poster_url: '/shader.webp', clip_url: '/shader.mp4' }],
    })
    expect(selectUiShowcase(summary.items)[0]?.name.zh).toBe('黑洞视界')
  })

  it('loads the lightweight release artifact and forwards cancellation', async () => {
    const payload = { version: 1, total: 240, items: [] }
    const fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => payload })
    vi.stubGlobal('fetch', fetch)
    const signal = new AbortController().signal
    expect(await loadUiShowcaseCatalog(signal)).toEqual(payload)
    expect(fetch).toHaveBeenCalledExactlyOnceWith('/ui-library/dashboard.json', { signal })
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
