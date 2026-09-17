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

const origin = process.argv[2] || 'http://127.0.0.1:4179'
const screenshot = process.argv[3] || '/tmp/godot-contact-verified.png'
const resolvedIp = process.argv[4]
const interactionOnly = process.argv[5] === 'interaction-only'
const sceneQuery = process.env.CONTACT_SCENE_QUERY || ''
const browser = await chromium.launch({
  headless: true,
  executablePath: '/home/kaixxrua/.cache/ms-playwright/chromium-1234/chrome-linux64/chrome',
  args: resolvedIp ? ['--no-proxy-server', `--host-resolver-rules=MAP aigcnews.cn ${resolvedIp}`] : [],
})
const context = await browser.newContext({
  viewport: { width: 1280, height: 900 },
  deviceScaleFactor: 1,
  serviceWorkers: 'block',
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
const requests = []
page.on('pageerror', error => errors.push(String(error)))
page.on('request', request => { if (request.url().includes('/api/')) requests.push(request.url()) })
await page.goto(`${origin}/contact`, { waitUntil: 'domcontentloaded', timeout: 30000 })
const iframe = page.locator('.godot-contact-scene iframe')
try {
  await iframe.waitFor({ state: 'visible', timeout: 30000 })
} catch (error) {
  console.error(JSON.stringify({ currentUrl: page.url(), errors, requests, body: (await page.locator('body').innerText()).slice(0, 1000) }))
  throw error
}
if (sceneQuery) {
  await iframe.evaluate((element, query) => {
    const target = new URL(element.src)
    for (const [key, value] of new URLSearchParams(query)) target.searchParams.set(key, value)
    element.src = target.href
  }, sceneQuery)
}
await page.waitForTimeout(1000)
const frame = page.frames().find(candidate => candidate.url().includes('/camp-scene/index.html'))
if (!frame) throw new Error('Godot iframe did not navigate to camp-scene')
const enter = frame.locator('#quality-enter')
if (await enter.isVisible()) await enter.click()
const canvas = frame.locator('canvas')
await canvas.waitFor({ state: 'visible', timeout: 30000 })
if (interactionOnly) {
  await page.screenshot({ path: screenshot, fullPage: true })
  console.log(JSON.stringify({ iframe: await iframe.getAttribute('src'), frame: frame.url(), qualityDialogOpen: await frame.locator('#quality-dialog').evaluate(element => element.open), pageErrors: errors, screenshot }))
  await browser.close()
  process.exit(0)
}
await frame.locator('#loading').waitFor({ state: 'hidden', timeout: 90000 })
await page.waitForTimeout(3000)
const box = await canvas.boundingBox()
if (!box || box.width < 300 || box.height < 200) throw new Error(`Godot canvas has invalid size: ${JSON.stringify(box)}`)
await page.screenshot({ path: screenshot, fullPage: true })
console.log(JSON.stringify({ iframe: await iframe.getAttribute('src'), frame: frame.url(), canvas: box,
  trace: await canvas.getAttribute('data-startup-trace'), pageErrors: errors, screenshot }))
await browser.close()
