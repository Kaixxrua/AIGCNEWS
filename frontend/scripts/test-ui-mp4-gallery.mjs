import assert from 'node:assert/strict'
import { chromium } from 'playwright'
import { mkdir } from 'node:fs/promises'
import { resolve } from 'node:path'

const base = process.env.UI_LIBRARY_BASE_URL || 'http://127.0.0.1:4173'
const launch = { headless: true }
if (process.env.PLAYWRIGHT_CHANNEL) launch.channel = process.env.PLAYWRIGHT_CHANNEL
if (process.env.PLAYWRIGHT_EXECUTABLE_PATH) launch.executablePath = process.env.PLAYWRIGHT_EXECUTABLE_PATH
const browser = await chromium.launch(launch)
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, locale: 'zh-CN' })
const errors = []
const output = process.env.UI_GALLERY_REPORT_DIR
if (output) await mkdir(output, { recursive: true })
page.on('pageerror', error => errors.push(error.message))
await page.route('**/api/**', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify({ items: [], providers: [], features: {} }) }))

async function verifyVisiblePlayback() {
  const ids = await page.evaluate(() => new Promise(resolve => {
    const posters = [...document.querySelectorAll('.ui-library__poster')]
    const visible = new Map()
    const observer = new IntersectionObserver(entries => {
      for (const entry of entries) visible.set(entry.target.closest('[data-template-id]').dataset.templateId, entry.isIntersecting && entry.intersectionRatio > 0)
      if (visible.size === posters.length) {
        observer.disconnect()
        resolve([...visible].filter(([, shown]) => shown).map(([id]) => id))
      }
    })
    posters.forEach(poster => observer.observe(poster))
  }))
  assert.ok(ids.length > 0)
  await page.waitForFunction(expected => expected.every(id => {
    const video = document.querySelector(`[data-template-id="${id}"] video.is-ready`)
    return video && !video.paused && video.readyState >= 2
  }), ids, { timeout: 30_000 })
  assert.equal(await page.locator('video.ui-library__card-preview').count(), ids.length, 'all and only visible cards attach video')
  const frames = await page.locator('video.ui-library__card-preview').evaluateAll(videos => videos.map(video => [video.closest('[data-template-id]').dataset.templateId, video.getVideoPlaybackQuality().totalVideoFrames]))
  await page.waitForFunction(previous => previous.every(([id, frames]) => {
    const video = document.querySelector(`[data-template-id="${id}"] video`)
    return video && video.getVideoPlaybackQuality().totalVideoFrames > frames
  }), frames, { timeout: 10_000 })
  return ids.length
}
try {
  await page.goto(base + '/ui-library', { waitUntil: 'domcontentloaded' })
  await page.waitForFunction(() => document.querySelectorAll('.ui-library__card').length === 96)
  assert.equal(await page.locator('.ui-library iframe').count(), 0, 'gallery must not run component iframes')
  await page.waitForFunction(() => document.querySelectorAll('video.ui-library__card-preview.is-ready').length >= 1, null, { timeout: 30_000 })
  const attached = page.locator('video.ui-library__card-preview')
  assert.ok(await verifyVisiblePlayback() > 3, 'desktop gallery must play more than three visible clips')
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
  await verifyVisiblePlayback()

  await scrollBox.evaluate(element => { element.scrollTop = 0 })
  await first.scrollIntoViewIfNeeded()
  await verifyVisiblePlayback()
  await page.getByRole('button', { name: '暂停全部', exact: true }).click()
  await page.waitForFunction(() => !document.querySelector('video.ui-library__card-preview'))
  await page.getByRole('button', { name: '播放全部', exact: true }).click()
  await verifyVisiblePlayback()
  for (const width of [2474, 390, 1440]) {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 1086 })
    await scrollBox.evaluate(element => { element.scrollTop = 0 })
    await first.scrollIntoViewIfNeeded()
    const count = await verifyVisiblePlayback()
    assert.ok(width === 390 || count > 3)
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false)
    if (output) await page.screenshot({ path: resolve(output, `gallery-${width}.png`) })
    console.log(`Viewport ${width}: ${count} visible videos decoded and advancing.`)
  }
  await first.locator('.ui-library__preview-trigger').click()
  await page.locator('dialog.ui-detail iframe').waitFor({ timeout: 30_000 })
  assert.ok(await attached.evaluateAll(videos => videos.every(video => video.paused)), 'detail pauses the gallery')
  assert.deepEqual(errors, [])
  console.log('MP4 gallery verified: all visible clips play, pause/resume works, offscreen clips release, and detail remains interactive.')
} finally {
  await browser.close()
}
