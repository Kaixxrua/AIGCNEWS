import assert from 'node:assert/strict'
import { chromium } from 'playwright'
import { mkdir } from 'node:fs/promises'

const base = process.env.UI_LIBRARY_BASE_URL || 'http://127.0.0.1:18793'
const output = process.env.UI_GALLERY_REPORT_DIR
if (output) await mkdir(output, { recursive: true })
const browser = await chromium.launch({ headless: true })
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, locale: 'zh-CN' })
  await page.route('**/api/**', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify({ items: [], providers: [], features: {} }) }))
  await page.goto(base + '/ui-library/kokonut-background-paths')
  const dialog = page.locator('dialog.ui-detail')
  const video = dialog.locator('video')
  await video.waitFor()
  await page.waitForFunction(() => document.querySelector('dialog video')?.currentTime > 0)
  assert.equal(await dialog.locator('iframe').count(), 0)
  assert.equal(await video.evaluate(v => v.loop && v.muted && !v.paused), true)
  // Observe real time wrapping twice; checking the loop attribute alone misses stalls.
  await video.evaluate(v => {
    window.previewLoops = 0
    let previous = v.currentTime
    v.addEventListener('timeupdate', () => {
      if (v.currentTime < previous) window.previewLoops++
      previous = v.currentTime
    })
  })
  await page.waitForFunction(() => window.previewLoops >= 2, null, { timeout: 20_000 })
  assert.equal(await video.evaluate(v => v.paused || v.ended), false)
  await dialog.getByRole('button', { name: '暂停', exact: true }).click()
  assert.equal(await video.count(), 0)
  await dialog.getByRole('button', { name: '播放', exact: true }).first().click()
  await page.waitForFunction(() => document.querySelector('dialog video')?.currentTime > 0)
  await dialog.getByRole('button', { name: '交互预览', exact: true }).click()
  await dialog.locator('iframe').waitFor()
  assert.equal(await video.count(), 0)
  await dialog.getByRole('button', { name: '视频预览', exact: true }).click()
  await page.waitForFunction(() => document.querySelector('dialog video')?.currentTime > 0)
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 1000 })
    const bounds = await video.boundingBox()
    assert.ok(bounds.width > 0 && bounds.x >= 0 && bounds.x + bounds.width <= width)
    if (output) await page.screenshot({ path: `${output}/loop-${width}.png` })
  }
  console.log('Kokonut detail loops twice; pause, resume, interactive mode, desktop and mobile pass.')
} finally {
  await browser.close()
}
