// @vitest-environment node
import type { IndexHtmlTransformContext, ResolvedConfig } from 'vite'
import { describe, expect, it } from 'vitest'
import { DESKTOP_STYLES_MEDIA as RUNTIME_MEDIA } from '../src/theme/desktopStyles'
import { DESKTOP_STYLES_MEDIA, desktopStylesPreload, isDesktopStylesAsset } from './desktopStylesPreload'

type Handler = (html: string, ctx: IndexHtmlTransformContext) => unknown

function run(bundle: Record<string, { type: 'asset' | 'chunk'; fileName: string }>, base = '/') {
  const plugin = desktopStylesPreload()
  ;(plugin.configResolved as (config: ResolvedConfig) => void)({ base } as ResolvedConfig)
  const { handler } = plugin.transformIndexHtml as { handler: Handler }
  return handler('<html></html>', { path: '/index.html', filename: 'index.html', bundle } as unknown as IndexHtmlTransformContext)
}

describe('desktop styles preload', () => {
  it('preloads the comic page sheet under the same media query the app attaches it with', () => {
    expect(DESKTOP_STYLES_MEDIA).toBe(RUNTIME_MEDIA)
    const bundle = {
      'assets/index-a.css': { type: 'asset' as const, fileName: 'assets/index-a.css' },
      'assets/comic-pages-BCpOub4t.css': { type: 'asset' as const, fileName: 'assets/comic-pages-BCpOub4t.css' },
    }
    expect(run(bundle)).toEqual([{
      tag: 'link',
      attrs: { rel: 'preload', as: 'style', href: '/assets/comic-pages-BCpOub4t.css', media: '(min-width: 1024px)' },
      injectTo: 'head',
    }])
    expect(run(bundle, '/app/')).toMatchObject([{ attrs: { href: '/app/assets/comic-pages-BCpOub4t.css' } }])
  })

  it('fails the build when the sheet was not emitted on its own', () => {
    expect(() => run({ 'assets/index-a.css': { type: 'asset', fileName: 'assets/index-a.css' } })).toThrow(/comic-pages/)
  })

  it('recognises only the emitted stylesheet', () => {
    expect(isDesktopStylesAsset('assets/comic-pages-BCpOub4t.css')).toBe(true)
    expect(isDesktopStylesAsset('assets/comic-pages-BCpOub4t.js')).toBe(false)
    expect(isDesktopStylesAsset('assets/index-BCpOub4t.css')).toBe(false)
    expect(isDesktopStylesAsset('comic-pages-BCpOub4t.css')).toBe(false)
  })
})
