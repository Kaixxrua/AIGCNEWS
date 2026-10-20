/// <reference types="node" />
import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const robots = readFileSync('public/robots.txt', 'utf8')
const rules = [...robots.matchAll(/^(Allow|Disallow):\s*(\S+)/gm)].map(([, action, path]) => {
  const pattern = path!.replace(/\$$/, '').split('*')
    .map(part => part.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('.*')
  return { allow: action === 'Allow', length: path!.length, regex: new RegExp('^' + pattern + (path!.endsWith('$') ? '$' : '')) }
})

// Google uses the longest matching rule; Allow wins ties. Unlike Python's
// RobotFileParser, this includes Google's * and $ semantics and the query.
function canFetch(path: string): boolean {
  return rules.filter(rule => rule.regex.test(path))
    .sort((a, b) => b.length - a.length || Number(b.allow) - Number(a.allow))[0]?.allow ?? true
}

describe('public crawler access', () => {
  it('uses one shared policy for Googlebot, Bingbot and other crawlers', () => {
    expect(robots.match(/^User-agent:.*$/gm)).toEqual(['User-agent: *'])
  })

  it.each([
    '/', '/?tab=news&lang=en-US', '/?tab=news&lang=zh-CN', '/projects', '/report?date=2026-10-19', '/papers/example/read',
    '/assets/app.js', '/assets/app.css', '/fonts/font.woff2',
    '/api/features', '/api/dashboard/summary-static?period=daily',
    '/api/dashboard/top?tab=arxiv&period=daily&locale=zh',
    '/api/dashboard/snapshot-dates?tab=arxiv', '/api/dashboard/new-words?date=2026-10-19',
    '/api/dashboard/live-stats', '/api/dashboard/x/recent?limit=20',
    '/api/projects', '/api/projects?source=github&page=1', '/api/projects/categories?source=github',
    '/api/projects/taxonomy', '/api/projects/github/logo/owner/repo',
    '/api/papers/example?locale=en', '/api/papers/arxiv/2601.12345',
    '/api/report/preview?source=all&date=2026-10-19&locale=zh',
    '/api/report/public', '/api/report/public?source=news&date=2026-10-19&locale=en-US',
    '/api/report/archive', '/api/report/archive?source=news&date=2026-10-19&locale=en-US',
    '/api/site/contact-page', '/api/site/recommended-websites', '/api/media/site/image.png',
    '/api/media/x/img/pbs.twimg.com/media/example.jpg',
    '/api/ui-library/catalog?summary=true', '/api/ui-library/catalog?template_id=demo%3Acard',
    '/api/ui-library/dashboard?limit=8', '/api/ui-library/engagement?period=daily',
    '/api/ui-library/icons', '/api/feed.xml', '/api/feeds/briefing.xml?locale=zh',
  ])('allows the page or public rendering resource %s', path => {
    expect(canFetch(path)).toBe(true)
  })

  it.each([
    '/api/auth/me', '/api/auth/login', '/api/oauth/authorize',
    '/api/ops/tasks', '/api/monitor/tasks', '/api/projects/me/collection',
    '/api/projects/me/favorites?source=github', '/api/projects/categories/private',
    '/api/projects/adoptions', '/api/projects/github/peek?repo=owner/repo',
    '/api/papers/search?q=agent', '/api/search?q=agent',
    '/api/report/latest', '/api/report/daily/stream', '/api/report/subscriptions',
    '/api/report/archive/private', '/api/report/public/private',
    '/api/dashboard/live-events', '/api/dashboard/visit',
    '/api/chat/stream', '/api/payments/orders/123', '/api/tracking',
    '/api/ui-library/copy-quota', '/api/ui-library/copy',
    '/api/feeds/briefing-digest.xml?token=private', '/api/mcp',
    '/api/media/x/proxy?url=https://example.com/image.png',
  ])('keeps private, metered and streaming endpoints out of crawling: %s', path => {
    expect(canFetch(path)).toBe(false)
  })

  it('advertises crawlable sitemaps with canonical public pages and working discovery links', () => {
    const sitemaps = [...robots.matchAll(/^Sitemap:\s*(\S+)/gm)].map(match => match[1]!)
    expect(sitemaps).toEqual(['https://aigcnews.cn/sitemap.xml', 'https://aigcnews.cn/api/sitemap.xml'])
    sitemaps.forEach(url => expect(canFetch(new URL(url).pathname)).toBe(true))
    const xml = new DOMParser().parseFromString(readFileSync('public/sitemap.xml', 'utf8'), 'application/xml')
    expect(xml.querySelector('parsererror')).toBeNull()
    const locations = [...xml.querySelectorAll('loc')].map(loc => loc.textContent!)
    const paths = ['/', '/projects', '/ui-library', '/report', '/mcp', '/dsh', '/x', '/disclaimer', '/privacy',
      '/?lang=zh-CN', '/?lang=en-US', '/?tab=news', '/?tab=news&lang=zh-CN', '/?tab=news&lang=en-US',
      '/report?lang=zh-CN', '/report?lang=en-US']
    expect(locations.sort()).toEqual(paths.map(path => 'https://aigcnews.cn' + path).sort())
    const html = new DOMParser().parseFromString(readFileSync('index.html', 'utf8'), 'text/html')
    const discoveryLinks = [...html.querySelectorAll('noscript a')].map(link => link.getAttribute('href'))
    for (const url of locations) {
      expect(canFetch(new URL(url).pathname + new URL(url).search)).toBe(true)
      if (url !== 'https://aigcnews.cn/') expect(discoveryLinks).toContain(url)
    }
  })
})
