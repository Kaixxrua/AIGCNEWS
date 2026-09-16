// Capture actual upstream renders; never synthesize or redraw thumbnail artwork.
import { chromium } from 'playwright'
import { readFile, mkdir, writeFile } from 'node:fs/promises'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const data = resolve(root, '../mcp-go/internal/uicatalog/data')
const base = process.env.UI_LIBRARY_BASE_URL || 'http://127.0.0.1:18782'
const { items } = JSON.parse(await readFile(resolve(data, 'catalog.json'), 'utf8'))
const prefixes = process.argv.slice(2)
const selected = items.filter(item => !prefixes.length || prefixes.some(prefix => item.id.startsWith(prefix)))
const posters = resolve(data, 'posters')
await mkdir(posters, { recursive: true })
const browser = await chromium.launch({
  ...(process.env.PLAYWRIGHT_CHANNEL ? { channel: process.env.PLAYWRIGHT_CHANNEL } : {}),
  ...(process.env.PLAYWRIGHT_EXECUTABLE_PATH ? { executablePath: process.env.PLAYWRIGHT_EXECUTABLE_PATH } : {}),
  headless: true,
  args: ['--enable-unsafe-swiftshader'],
})
const results = []
try {
  for (const item of selected) {
    const page = await browser.newPage({ viewport: { width: 640, height: 480 }, deviceScaleFactor: 1 })
    const errors = []
    page.on('pageerror', error => errors.push(error.message))
    page.on('console', message => { if (message.type() === 'error') errors.push(message.text()) })
    page.on('requestfailed', request => errors.push(request.url() + ': ' + request.failure()?.errorText))
    await page.setContent(`<!doctype html><html lang="en"><style>html,body{margin:0;width:100%;height:100%}iframe{width:100%;height:100%;border:0;display:block}</style><script>window.previewState='loading';window.addEventListener('message',e=>{if(e.data?.type==='ui-library-preview')window.previewState=e.data.state})</script><iframe title="Original effect" sandbox="allow-scripts" src="${base}${item.preview_url}"></iframe></html>`)
    await page.waitForFunction(() => window.previewState !== 'loading', null, { timeout: 30000 })
    // Let the original animation progress before taking a real screenshot.
    await page.mouse.move(380, 240)
    await page.waitForTimeout(2200)
    const state = await page.evaluate(() => window.previewState)
    await page.locator('iframe').screenshot({ path: resolve(posters, `${item.id}.png`) })
    results.push({ id: item.id, state, errors })
    console.log(JSON.stringify(results.at(-1)))
    await page.close()
  }
} finally {
  await browser.close()
  await writeFile(resolve(root, '.ui-previews/render-report.json'), JSON.stringify(results, null, 2))
}
if (results.some(item => item.state !== 'ready' || item.errors.length)) process.exitCode = 1
