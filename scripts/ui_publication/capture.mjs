// Original HTML is rendered only inside a sandbox with outbound requests blocked.
import { chromium } from 'playwright'
import { readFile, writeFile } from 'node:fs/promises'
import { resolve } from 'node:path'
const data = resolve('../mcp-go/internal/uicatalog/data')
const ids = JSON.parse(await readFile(process.env.UI_PREVIEW_IDS_FILE, 'utf8'))
const { items } = JSON.parse(await readFile(resolve(data, 'catalog.json'), 'utf8'))
const browser = await chromium.launch({ channel: 'chrome', headless: true })
const results = []
try {
  const page = await browser.newPage({ viewport: { width: 640, height: 400 } })
  await page.route('**/*', route => route.request().url().startsWith(process.env.UI_LIBRARY_BASE_URL + '/') ? route.continue() : route.abort())
  let errors = []
  page.on('pageerror', error => errors.push(error.message))
  page.on('requestfailed', request => errors.push('request_failed:' + request.url()))
  for (const item of items.filter(item => ids.includes(item.id))) {
    errors = []
    let state = 'error'
    try {
      await page.setContent(`<style>html,body{margin:0}iframe{width:640px;height:400px;border:0}</style><script>window.state='loading';window.addEventListener('message',e=>{if(e.source===document.querySelector('iframe').contentWindow && e.data?.type==='ui-library-preview')window.state=e.data.state})</script><iframe sandbox="allow-scripts" src="${process.env.UI_LIBRARY_BASE_URL}${item.preview_url}"></iframe>`)
      await page.waitForFunction(() => window.state !== 'loading', null, { timeout: 15000 })
      state = await page.evaluate(() => window.state)
      await page.screenshot({ path: resolve(data, 'posters', item.id + '.png') })
    } catch (error) { errors.push(error.message) }
    results.push({ id: item.id, state, errors: [...errors] })
  }
} finally {
  await browser.close()
  await writeFile(process.env.UI_RENDER_REPORT_FILE, JSON.stringify(results, null, 2))
}
console.log(JSON.stringify({ rendered: results.length, failed: results.filter(row => row.state !== 'ready' || row.errors.length).length }))
