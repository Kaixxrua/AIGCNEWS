import assert from 'node:assert/strict'
import { chromium } from 'playwright'
import { mkdir, readFile } from 'node:fs/promises'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const base = process.env.UI_LIBRARY_BASE_URL || 'http://127.0.0.1:18782'
const output = resolve(root, '../test-results/ui-library')
await mkdir(output, { recursive: true })
const { items } = JSON.parse(await readFile(resolve(root, '../mcp-go/internal/uicatalog/data/catalog.json'), 'utf8'))
const browser = await chromium.launch({
  ...(process.env.PLAYWRIGHT_CHANNEL ? { channel: process.env.PLAYWRIGHT_CHANNEL } : {}),
  headless: true, ignoreDefaultArgs: ['--hide-scrollbars'], args: ['--enable-unsafe-swiftshader'],
})
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, locale: 'zh-CN', ignoreHTTPSErrors: true })
await context.grantPermissions(['clipboard-read', 'clipboard-write'], { origin: base })
const page = await context.newPage()
// Gallery regression isolates auth/engagement; account behavior has its own browser suite.
await context.addInitScript(() => { if (window.top === window) localStorage.setItem('auth_token', 'gallery-test-token') })
await page.route('**/api/**', async route => {
  const path = new URL(route.request().url()).pathname
  let data = { items: [], providers: [], features: {} }
  if (path === '/api/auth/me') data = { user_id: 1, email: 'gallery@example.test', role: 'user', membership_tier: 'member' }
  if (path.endsWith('/copy-quota') || path.endsWith('/copy')) data = { used: 0, limit: null, remaining: null, resets_at: null }
  await route.fulfill({ contentType: 'application/json', body: JSON.stringify(data) })
})
const errors = []
page.on('pageerror', error => errors.push(error.message))
const search = page.locator('.ui-library__search input')
const cards = page.locator('.ui-library__card')
const dialog = page.locator('dialog.ui-detail')
const waitCount = count => page.waitForFunction(n => document.querySelectorAll('.ui-library__card').length === n, count)
// Windows text clipboards normalize LF to CRLF; source transport is checked separately.
const clipboard = async () => (await page.evaluate(() => navigator.clipboard.readText())).replace(/\r\n/g, '\n')
let releaseSlowPreview
const slowPreview = new Promise(resolve => { releaseSlowPreview = resolve })
await page.route('**' + items[0].clip_url, async route => { await slowPreview; await route.continue() })
try {
  await page.goto(base + '/ui-library', { waitUntil: 'domcontentloaded' })
  await waitCount(30)
  const scrollBox = page.locator('.ui-library')
  assert.equal(await scrollBox.evaluate(el => getComputedStyle(el).overflowY), 'auto', 'gallery must override the layout overflow clipping')
  assert.ok(await scrollBox.evaluate(el => el.offsetWidth - el.clientWidth >= 10), 'reserve a visible scrollbar on the right')
  await cards.first().locator('.ui-library__poster').hover()
  await page.mouse.wheel(0, 380)
  await page.waitForFunction(() => document.querySelector('.ui-library').scrollTop >= 300)
  await page.mouse.wheel(0, -10000)
  await page.waitForFunction(() => document.querySelector('.ui-library').scrollTop === 0)
  await page.locator('.ui-library__poster img').evaluateAll(images => Promise.all(images.map(async img => { img.loading = 'eager'; await img.decode() })))
  await page.screenshot({ path: resolve(output, 'gallery-desktop.png') })
  assert.equal(await page.locator('.ui-library .ui-mcp-tip a').getAttribute('href'), '/mcp')
  const first = cards.first()
  const hoverFrames = page.locator('.ui-library__card-preview')
  const visibleIds = () => page.evaluate(() => new Promise(resolve => {
    const posters = [...document.querySelectorAll('.ui-library__poster')]
    const seen = new Map()
    const observer = new IntersectionObserver(entries => {
      for (const entry of entries) seen.set(entry.target.closest('[data-template-id]').dataset.templateId, entry.isIntersecting && entry.intersectionRatio > 0)
      if (seen.size === posters.length) { observer.disconnect(); resolve([...seen].filter(([, visible]) => visible).map(([id]) => id).sort()) }
    })
    posters.forEach(poster => observer.observe(poster))
  }))
  const waitVisiblePlayback = async () => {
    const ids = await visibleIds()
    await page.waitForFunction(expected => {
      return expected.every(id => document.querySelector(`[data-template-id="${id}"] video.ui-library__card-preview`))
    }, ids)
    return ids
  }
  assert.equal(await page.locator('.ui-library iframe').count(), 0, 'dense gallery should not allocate WebGL contexts')
  const initialVisible = await waitVisiblePlayback()
  assert.ok(initialVisible.length >= 3 && initialVisible.length < 30, 'all visible cards receive MP4 previews')
  assert.ok(await hoverFrames.count() < 30, 'only the viewport and a small look-ahead window attach media')
  // Exceed the old 15-second cutoff: pending downloads must remain recoverable.
  await page.waitForTimeout(16000)
  assert.equal(await first.getAttribute('data-preview-state'), 'loading')
  assert.equal(await first.locator('video').count(), 1, 'slow loading must not destroy the preview')
  assert.equal(await first.locator('video').evaluate(el => getComputedStyle(el).opacity), '0', 'keep the static cover until ready')
  assert.ok(await page.locator('.ui-library__card-preview.is-ready').count() > 0, 'ready cards play independently of pending cards')
  await page.screenshot({ path: resolve(output, 'gallery-loading-cover.png') })
  releaseSlowPreview()
  await first.locator('video.is-ready').waitFor()
  await page.screenshot({ path: resolve(output, 'gallery-autoplay.png') })
  await search.hover()
  assert.ok(await hoverFrames.count() >= initialVisible.length, 'playback and look-ahead loading continue without hover')
  await page.locator('.ui-library').evaluate(el => { el.scrollTop = el.scrollHeight })
  await cards.last().locator('.ui-library__poster').scrollIntoViewIfNeeded()
  const bottomVisible = await waitVisiblePlayback()
  assert.ok(bottomVisible.includes(items.at(-1).id))
  assert.ok(!bottomVisible.includes(items[0].id))
  assert.equal(await first.locator('video').count(), 1, 'loaded MP4 stays warm for instant back-scroll')
  assert.equal(await first.locator('video').evaluate(video => video.paused), true, 'offscreen MP4 pauses')
  await page.locator('.ui-library').evaluate(el => { el.scrollTop = 0 })
  await first.locator('.ui-library__poster').scrollIntoViewIfNeeded()
  await waitVisiblePlayback()
  await page.getByRole('button', { name: '暂停全部', exact: true }).click()
  await page.waitForFunction(() => [...document.querySelectorAll('video.ui-library__card-preview')].every(video => video.paused))
  await page.getByRole('button', { name: '播放全部', exact: true }).click()
  await waitVisiblePlayback()
  await first.locator('.ui-library__copy-source').click()
  await first.getByRole('status').waitFor()
  const bundle = await clipboard()
  for (const file of [...items[0].files, ...items[0].notices]) {
    assert.ok(bundle.includes(file.name))
    assert.ok(bundle.includes(await readFile(resolve(root, '../mcp-go/internal/uicatalog/data', file.path), 'utf8')))
  }
  await first.locator('.ui-library__copy-prompt').click()
  await page.waitForFunction(() => document.querySelector('.ui-library__copy-prompt')?.textContent.includes('已复制'))
  assert.ok((await clipboard()).includes('请把') && (await clipboard()).includes(items[0].revision))
  await search.focus()
  await search.fill('液态金属'); await waitCount(2)
  const chinese = await cards.evaluateAll(elements => elements.map(el => el.dataset.templateId))
  await search.fill('liquid metal'); await waitCount(2)
  assert.deepEqual(await cards.evaluateAll(elements => elements.map(el => el.dataset.templateId)), chinese)
  await search.fill('silk'); await waitCount(1)
  await page.locator('.ui-library__framework select').selectOption('react')
  await page.locator('.ui-library__empty h2').waitFor()
  assert.equal(await cards.count(), 0)
  await page.locator('.ui-library__results').getByRole('button', { name: '清除筛选', exact: true }).click(); await waitCount(30)

  await page.getByRole('button', { name: '预览效果: 液态金属', exact: true }).click()
  await dialog.waitFor()
  await dialog.locator('pre code').waitFor()
  assert.ok(await hoverFrames.evaluateAll(videos => videos.every(video => video.paused)), 'detail preview pauses gallery videos')
  assert.ok(await dialog.locator('pre code .hljs-keyword').count() > 0, 'source must be syntax highlighted')
  await dialog.locator('.ui-detail__preview-status').waitFor({ state: 'hidden', timeout: 30000 })
  assert.equal(await dialog.locator('.ui-detail__preview-error').count(), 0)
  const item = items.find(item => item.id === 'paper-liquid-metal')
  const original = await readFile(resolve(root, '../mcp-go/internal/uicatalog/data', item.files[0].path), 'utf8')
  assert.equal(await dialog.locator('pre code').textContent(), original)
  assert.ok((await dialog.locator('.ui-source-viewer__gutter').textContent()).startsWith('1\n2\n3'))
  await dialog.locator('.ui-detail__copy-source').click()
  assert.equal(await clipboard(), original)
  await dialog.locator('.ui-detail__copy-prompt').click()
  const zhPrompt = await clipboard()
  assert.ok(zhPrompt.includes('请把') && zhPrompt.includes(item.revision) && zhPrompt.includes(original))
  for (const file of item.files) assert.ok(zhPrompt.includes(file.name))
  await dialog.getByLabel('提示词语言').selectOption('en')
  await dialog.locator('.ui-detail__copy-prompt').click()
  assert.ok((await clipboard()).startsWith('Integrate '))
  await page.screenshot({ path: resolve(output, 'detail-highlighted.png') })
  await dialog.locator('.ui-detail__filebar select').selectOption('1')
  await dialog.locator('.ui-detail__copy-source').click()
  assert.equal(await clipboard(), await readFile(resolve(root, '../mcp-go/internal/uicatalog/data', item.files[1].path), 'utf8'))
  await page.screenshot({ path: resolve(output, 'detail-desktop.png') })

  await dialog.getByRole('button', { name: '暂停', exact: true }).click()
  assert.equal(await dialog.locator('iframe').count(), 0)
  await dialog.locator('.ui-detail__preview-toolbar button[aria-label="播放"]').click()
  await dialog.getByRole('button', { name: '手机', exact: true }).click()
  assert.ok((await dialog.locator('iframe').boundingBox()).width <= 320)

  for (const width of [1024, 768, 320]) {
    await page.setViewportSize({ width, height: 960 })
    assert.ok(await dialog.evaluate(el => el.scrollWidth <= el.clientWidth + 1), 'dialog overflows at ' + width)
    await page.screenshot({ path: resolve(output, 'detail-' + width + '.png') })
  }
  await page.keyboard.press('Escape')
  await dialog.waitFor({ state: 'detached' })
  assert.equal(await page.evaluate(() => document.activeElement?.getAttribute('aria-label')), '预览效果: 液态金属')
  for (const width of [320, 768, 1024, 1440]) {
    await page.setViewportSize({ width, height: 1000 })
    const visible = await waitVisiblePlayback()
    assert.ok(visible.length > 0, 'visible effects autoplay at ' + width)
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), 'page overflows at ' + width)
    await page.screenshot({ path: resolve(output, 'gallery-' + width + '.png') })
  }
  for (const [width, columns] of [[1440, 4], [1920, 6], [2474, 8]]) {
    await page.setViewportSize({ width, height: 1086 })
    await scrollBox.evaluate(el => { el.scrollTop = 0 })
    const visible = await waitVisiblePlayback()
    assert.equal(await page.locator('.ui-library__grid').evaluate(el => getComputedStyle(el).gridTemplateColumns.split(' ').length), columns)
    assert.ok(await scrollBox.evaluate(el => {
      const bounds = el.getBoundingClientRect()
      return [...el.querySelectorAll('.ui-library__card')].filter(card => { const rect = card.getBoundingClientRect(); return rect.top >= bounds.top && rect.bottom <= bounds.bottom }).length
    }) >= columns * 2, 'show at least two complete rows at ' + width)
    await page.waitForFunction(ids => ids.every(id => {
      const video = document.querySelector(`[data-template-id="${id}"] video.is-ready`)
      return video && !video.paused && video.currentTime > 0
    }), visible, { timeout: 30000 })
    await page.screenshot({ path: resolve(output, 'gallery-dense-' + width + '.png') })
  }
  await page.setViewportSize({ width: 1440, height: 1000 })
  await page.evaluate(() => document.documentElement.setAttribute('data-theme', 'dark'))
  await page.screenshot({ path: resolve(output, 'gallery-dark.png') })
  await page.evaluate(() => localStorage.setItem('app_locale', 'en-US'))
  await page.reload(); await waitCount(30)
  assert.equal(await page.locator('.ui-library h1').innerText(), 'UI Library')
  await search.fill('液态金属'); await waitCount(2)

  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.goto(base + '/ui-library/threeui-liquid-form')
  await dialog.locator('pre code').waitFor()
  assert.equal(await dialog.locator('iframe').count(), 0, 'reduced-motion should wait for explicit play')
  await page.keyboard.press('Escape')
  await waitVisiblePlayback()
  assert.ok(await hoverFrames.count() > 0, 'gallery defaults to autoplay independently of system motion preferences')
  await page.emulateMedia({ reducedMotion: 'no-preference' })

  let failCatalog = true
  await page.route('**/ui-library/catalog.json', route => failCatalog ? route.fulfill({ status: 503, body: 'unavailable' }) : route.continue())
  await page.reload()
  await page.locator('.ui-library__empty[role="alert"]').waitFor()
  failCatalog = false
  await page.getByRole('button', { name: 'Retry', exact: true }).click(); await waitCount(30)
  await page.unroute('**/ui-library/catalog.json')

  await page.route('**/' + item.files[0].path, route => route.fulfill({ status: 503, body: 'unavailable' }))
  const failedCard = page.locator(`[data-template-id="${item.id}"]`)
  const previousClipboard = await clipboard()
  await failedCard.locator('.ui-library__copy-source').click()
  await failedCard.getByRole('status').waitFor()
  assert.equal(await failedCard.getByRole('status').textContent(), 'Source could not be loaded')
  assert.equal(await clipboard(), previousClipboard, 'failed download must not overwrite the clipboard')
  await page.goto(base + '/ui-library/' + item.id)
  await dialog.locator('.ui-detail__code-message[role="alert"]').waitFor()
  assert.equal(await dialog.locator('.ui-detail__copy-source').isDisabled(), true)
  await page.unroute('**/' + item.files[0].path)
  await dialog.getByRole('button', { name: 'Retry', exact: true }).click()
  await dialog.locator('pre code').waitFor()
  await page.keyboard.press('Escape')

  await page.goto(base + '/ui-library/unknown-template')
  await page.locator('.ui-library__not-found').waitFor()
  await page.getByRole('button', { name: 'Back to library', exact: true }).click()
  await page.locator('.ui-library__not-found').waitFor({ state: 'detached' })
  await page.locator('.ui-library .ui-mcp-tip a').click()
  await page.waitForURL('**/mcp')
  await page.goto(base + '/ui-library/' + item.id)
  await dialog.waitFor()
  await dialog.locator('.ui-mcp-tip a').click()
  await page.waitForURL('**/mcp')
  assert.equal(await dialog.count(), 0, 'MCP navigation closes the detail dialog')
  assert.deepEqual(errors, [])
  console.log('UI library browser checks passed: visible scrollbar and mouse wheel, 4/6/8-column density, default autoplay, slow-loading recovery, offscreen cleanup, clipboard, responsive layouts and MCP navigation.')
} finally {
  releaseSlowPreview()
  await browser.close()
}
