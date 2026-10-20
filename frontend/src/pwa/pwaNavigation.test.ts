// @vitest-environment node
import { afterAll, describe, expect, it, vi } from 'vitest'
import { NavigationRoute } from 'workbox-routing/NavigationRoute'
import { serverDocumentNavigationDenylist } from './serverDocuments'

vi.hoisted(() => {
  vi.stubGlobal('self', { __WB_DISABLE_DEV_LOGS: true })
})
afterAll(() => vi.unstubAllGlobals())

// Exercise Workbox with the same document policy imported by the production
// build. CI deliberately overlays vite.config.ts with its trusted gate config.
const navigation = new NavigationRoute(async () => new Response('shell'), {
  denylist: serverDocumentNavigationDenylist,
})

const matches = (path: string) => navigation.match({
  url: new URL(path, 'https://aigcnews.cn'),
  request: { mode: 'navigate' } as Request,
} as Parameters<typeof navigation.match>[0])

describe('PWA navigation boundaries', () => {
  it.each([
    '/sitemap.xml', '/sitemap.xml?refresh=1', '/robots.txt', '/robots.txt?v=2',
  ])('leaves the server document untouched: %s', path => {
    expect(matches(path)).toBe(false)
  })

  it.each([
    '/', '/?tab=news&lang=en-US', '/report?date=2026-10-20&type=news',
    '/projects', '/papers/2601.12345/read',
  ])('preserves offline application navigation: %s', path => {
    expect(matches(path)).toBe(true)
  })
})
