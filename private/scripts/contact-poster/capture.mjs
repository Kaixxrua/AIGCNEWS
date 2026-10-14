import { createRequire } from 'node:module'
import { writeFileSync } from 'node:fs'
const require = createRequire('/home/kaixxrua/AIGCNEWS/frontend/')
const { chromium } = require('playwright')
const [W, H, quality = 'original', out = 'poster.png', settleFrames = '90'] = process.argv.slice(2)
const log = (...a) => console.log(new Date().toISOString().slice(11, 19), ...a)
const browser = await chromium.launch({ headless: true, executablePath: '/home/kaixxrua/.cache/ms-playwright/chromium-1234/chrome-linux64/chrome',
  args: ['--no-proxy-server', '--enable-unsafe-swiftshader', '--disable-background-timer-throttling', '--disable-renderer-backgrounding'] })
const context = await browser.newContext({ viewport: { width: +W, height: +H }, deviceScaleFactor: 1, serviceWorkers: 'block' })
// Frame clock inside the scene iframe only: once rendering gets heavy (software GL),
// performance.now advances a fixed 17.5ms per rendered frame so the adaptive
// governor sees ~57 FPS and keeps full render scale; loading phase stays real-time.
await context.addInitScript(() => {
  if (!location.pathname.startsWith('/camp-scene/')) return
  // Software GL blocks the main thread for seconds per frame; stretch the
  // scene's long watchdogs (actor 30s, fetch 60s) so they don't fire spuriously.
  const realSetTimeout = window.setTimeout.bind(window)
  window.setTimeout = (fn, ms, ...rest) => realSetTimeout(fn, ms >= 20000 ? ms * 20 : ms, ...rest)
  const real = performance.now.bind(performance)
  let mode = 'real', vBase = real(), rBase = real(), lastTs = -1, frames = 0, heavy = 0
  const STEP = 17.5
  const now = () => mode === 'real' ? real() : vBase + Math.min(real() - rBase, 1)
  performance.now = now
  const raf = window.requestAnimationFrame.bind(window)
  window.requestAnimationFrame = cb => raf(ts => {
    if (ts !== lastTs) {
      lastTs = ts; frames++
      if (mode === 'frame') { vBase = vBase + STEP; rBase = real() }
    }
    const t0 = real(); const v = now()
    try { cb(v) } finally {
      if (mode === 'real' && real() - t0 > 250 && ++heavy >= 1) { mode = 'frame'; vBase = real(); rBase = real() }
    }
  })
  window.__clock = { get mode() { return mode }, get frames() { return frames } }
})
const page = await context.newPage()
page.on('console', m => { const t = m.text(); if (/error|fail|warn/i.test(m.type() + t)) log('console', m.type(), t.slice(0, 200)) })
page.on('pageerror', e => log('pageerror', String(e).slice(0, 300)))
await page.goto(`http://127.0.0.1:4191/?quality=${quality}`)
const t0 = Date.now()
let frame
while (!frame) { frame = page.frames().find(f => f.url().includes('/camp-scene/')); if (!frame) await page.waitForTimeout(200) }
let lastStatus = '', readyFrames = null
for (;;) {
  await page.waitForTimeout(5000)
  const st = await page.evaluate(() => window.__statuses.map(s => s[1]))
  const info = await frame.evaluate(() => ({ clock: window.__clock?.mode, frames: window.__clock?.frames,
    loading: document.getElementById('loading')?.hidden ?? null, loadingVisible: getComputedStyle(document.getElementById('loading')).display,
    msg: document.getElementById('loading-message')?.textContent, campStatus: document.getElementById('canvas')?.dataset.campStatus,
    perf: document.getElementById('scene-fps')?.textContent, scale: document.getElementById('canvas')?.dataset.renderScale, pmode: document.getElementById('canvas')?.dataset.performanceMode })).catch(e => ({ err: String(e).slice(0, 100) }))
  const status = st.at(-1) || ''
  log(Math.round((Date.now() - t0) / 1000) + 's', JSON.stringify(info), st.join('>'))
  if (status === 'ready' && readyFrames === null) readyFrames = info.frames
  if (readyFrames !== null && info.frames - readyFrames >= +settleFrames) break
  if (['error', 'unavailable', 'reload_required'].includes(status)) { log('bad status', status); break }
  if (Date.now() - t0 > 3 * 3600 * 1000) { log('timeout'); break }
}
await frame.addStyleTag({ content: '#scene-controls,#scene-fps,#loading,#camp-assets-retry,dialog,.sr-only{display:none!important}' })
await page.waitForTimeout(500)
await page.screenshot({ path: out, timeout: 900000, animations: 'allow' })
log('saved', out)
await browser.close()
