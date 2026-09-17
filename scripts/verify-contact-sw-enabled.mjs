// SW-enabled live verification for the /camp-scene navigation fallback fix.
// Unlike verify-contact-browser.mjs this does NOT block service workers:
// it loads /contact once to register the PWA worker, waits until the worker
// controls the page, reloads so the iframe navigation is intercepted by the
// worker, then asserts the Godot iframe really reaches /camp-scene/index.html.
import { createRequire } from 'node:module'
const require = createRequire(import.meta.url)
let chromium
for (const candidate of [
  process.env.PLAYWRIGHT_MODULE,
  'playwright',
  '/home/kaixxrua/AIGCNEWS/frontend/node_modules/playwright',
].filter(Boolean)) {
  try { ({ chromium } = require(candidate)); break } catch {}
}
if (!chromium) throw new Error('playwright module not found in candidate paths')

const origin = process.env.CONTACT_ORIGIN || 'https://aigcnews.cn'
const resolvedIp = process.argv[2]
const screenshot = process.argv[3] || '/tmp/godot-contact-sw-enabled.png'
const sceneQuery = process.env.CONTACT_SCENE_QUERY || ''
if (origin === 'https://aigcnews.cn' && !resolvedIp)
  throw new Error('usage: verify-contact-sw-enabled.mjs <resolved-ip> [screenshot]')

const browser = await chromium.launch({
  headless: true,
  executablePath: '/home/kaixxrua/.cache/ms-playwright/chromium-1234/chrome-linux64/chrome',
  args: ['--no-proxy-server', ...(resolvedIp ? [`--host-resolver-rules=MAP aigcnews.cn ${resolvedIp}`] : [])],
})
const context = await browser.newContext({
  viewport: { width: 1280, height: 900 },
  deviceScaleFactor: 1,
})
const page = await context.newPage()
await page.route('**/api/site/contact-page', route => route.fulfill({
  contentType: 'application/json',
  body: JSON.stringify({
    enabled: true,
    nav_label: '联系',
    title: '联系合作',
    subtitle: '外包 · 商务合作',
    service_cards: [],
    contact_entries: [{ label: '邮箱', value: 'hi@example.com', href: 'mailto:hi@example.com', qr_image_url: '' }],
    body_markdown: '',
    updated_at: null,
  }),
}))
const errors = []
page.on('pageerror', error => errors.push(String(error)))

await page.goto(`${origin}/contact`, { waitUntil: 'domcontentloaded', timeout: 45000 })
// First-time install precaches ~155 assets and can take minutes; wait generously.
await page.waitForFunction(() => !!navigator.serviceWorker?.controller, null, { timeout: 300000 })
const swScript = await page.evaluate(() => navigator.serviceWorker.controller.scriptURL)
// Reload so this navigation (and the iframe subrequest) is handled by the active worker.
await page.reload({ waitUntil: 'domcontentloaded', timeout: 45000 })
// Post-reload activation precaches ~155 assets and can take minutes; wait generously.
await page.waitForFunction(() => !!navigator.serviceWorker?.controller, null, { timeout: 300000 })

const iframe = page.locator('.godot-contact-scene iframe')
await iframe.waitFor({ state: 'visible', timeout: 30000 })
await page.waitForTimeout(1000)
const initialFrame = page.frames().find(candidate => candidate.url().includes('/camp-scene/index.html'))
if (!initialFrame) {
  const frameUrls = page.frames().map(candidate => candidate.url())
  console.error(JSON.stringify({ swScript, frameUrls, errors }))
  throw new Error('Godot iframe did not navigate to camp-scene (SW fallback regression)')
}
if (sceneQuery) {
  await iframe.evaluate((element, query) => {
    const target = new URL(element.src)
    for (const [key, value] of new URLSearchParams(query)) target.searchParams.set(key, value)
    element.src = target.href
  }, sceneQuery)
  await page.waitForTimeout(1000)
}
const frame = page.frames().find(candidate => candidate.url().includes('/camp-scene/index.html')
  && (!sceneQuery || [...new URLSearchParams(sceneQuery)].every(([key, value]) => new URL(candidate.url()).searchParams.get(key) === value)))
if (!frame) throw new Error('Godot iframe did not apply the isolated scene query')
const enter = frame.locator('#quality-enter')
if (await enter.isVisible()) await enter.click()
const canvas = frame.locator('canvas')
await canvas.waitFor({ state: 'visible', timeout: 60000 })
// Godot asset download shares bandwidth with the SW precache on first run; allow long load.
try {
  await frame.locator('#loading').waitFor({ state: 'hidden', timeout: 300000 })
} catch (error) {
  const text = await frame.locator('#loading').innerText().catch(() => '')
  console.error('loading-stuck:', JSON.stringify(text.slice(0, 300)))
  throw error
}
await page.waitForTimeout(3000)
const box = await canvas.boundingBox()
if (!box || box.width < 300 || box.height < 200) throw new Error(`Godot canvas has invalid size: ${JSON.stringify(box)}`)
await page.screenshot({ path: screenshot, fullPage: true })
console.log(JSON.stringify({ swScript, frame: frame.url(), canvas: box,
  trace: await canvas.getAttribute('data-startup-trace'), pageErrors: errors, screenshot }))
await browser.close()
