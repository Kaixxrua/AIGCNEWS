import assert from 'node:assert/strict'
import { chromium } from 'playwright'

const base = process.env.UI_LIBRARY_BASE_URL || 'http://127.0.0.1:4173'
const launch = { headless: true }
if (process.env.PLAYWRIGHT_CHANNEL) launch.channel = process.env.PLAYWRIGHT_CHANNEL
if (process.env.PLAYWRIGHT_EXECUTABLE_PATH) launch.executablePath = process.env.PLAYWRIGHT_EXECUTABLE_PATH
const browser = await chromium.launch(launch)
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, locale: 'zh-CN' })
const errors = []
page.on('pageerror', error => errors.push(error.message))
await page.route('**/api/**', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify({ items: [], providers: [], features: {} }) }))
try {
  await page.goto(base + '/ui-library', { waitUntil: 'domcontentloaded' })
  await page.waitForFunction(() => document.querySelectorAll('.ui-library__card').length === 96)
  assert.equal(await page.locator('.ui-library iframe').count(), 0, 'gallery must not run component iframes')
  await page.waitForFunction(() => document.querySelectorAll('video.ui-library__card-preview.is-ready').length >= 1, null, { timeout: 30_000 })
  const attached = page.locator('video.ui-library__card-preview')
  assert.ok(await attached.count() <= 3, 'mobile-safe scheduler caps active MP4 decoders')
  assert.ok((await attached.evaluateAll(videos => videos.map(video => video.getAttribute('src')))).every(source => source?.endsWith('.mp4')))
  const first = page.locator('.ui-library__card').first()
  assert.ok((await first.locator('img').getAttribute('src')).endsWith('.webp'))
  assert.equal(await first.locator('video').evaluate(video => video.paused), false)

  const scrollBox = page.locator('.ui-library')
  await scrollBox.evaluate(element => { element.scrollTop = element.scrollHeight })
  const last = page.locator('.ui-library__card').nth(95)
  await last.scrollIntoViewIfNeeded()
  await last.locator('video.is-ready').waitFor({ timeout: 30_000 })
  await page.waitForFunction(() => !document.querySelector('.ui-library__card')?.querySelector('video'))
  assert.equal(await first.locator('video').count(), 0, 'offscreen media is released for later cards')

  await scrollBox.evaluate(element => { element.scrollTop = 0 })
  await first.scrollIntoViewIfNeeded()
  await first.locator('.ui-library__preview-trigger').click()
  await page.locator('dialog.ui-detail iframe').waitFor({ timeout: 30_000 })
  assert.ok(await attached.evaluateAll(videos => videos.every(video => video.paused)), 'detail pauses the gallery')
  assert.deepEqual(errors, [])
  console.log(`MP4 gallery verified: ${await attached.count()} active clips, no list iframe, offscreen release and interactive detail.`)
} finally {
  await browser.close()
}
