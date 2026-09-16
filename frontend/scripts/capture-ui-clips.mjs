// Record the real upstream components for dense galleries; no generated artwork.
import { chromium } from 'playwright'
import { readFile, mkdir, writeFile, stat } from 'node:fs/promises'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { execFile } from 'node:child_process'
import { promisify } from 'node:util'

const run = promisify(execFile)
const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const data = resolve(root, '../mcp-go/internal/uicatalog/data')
const base = process.env.UI_LIBRARY_BASE_URL || 'http://127.0.0.1:18782'
const ffmpeg = process.env.FFMPEG_PATH || 'ffmpeg'
const { items } = JSON.parse(await readFile(resolve(data, 'catalog.json'), 'utf8'))
const prefixes = process.argv.slice(2)
const queue = items.filter(item => !prefixes.length || prefixes.some(prefix => item.id.startsWith(prefix)))
const clips = resolve(data, 'clips')
const recordings = resolve(root, '.ui-previews/recordings')
await mkdir(clips, { recursive: true })
await mkdir(recordings, { recursive: true })
const browser = await chromium.launch({ ...(process.env.PLAYWRIGHT_CHANNEL ? { channel: process.env.PLAYWRIGHT_CHANNEL } : {}), headless: true, args: ['--enable-unsafe-swiftshader'] })
const results = []
async function worker() {
  while (queue.length) {
    const item = queue.shift()
    const context = await browser.newContext({ viewport: { width: 640, height: 400 }, deviceScaleFactor: 1, recordVideo: { dir: recordings, size: { width: 640, height: 400 } } })
    try {
      const page = await context.newPage()
      const errors = []
      page.on('pageerror', error => errors.push(error.message))
      page.on('console', message => { if (message.type() === 'error' || /Too many active WebGL/.test(message.text())) errors.push(message.text()) })
      await page.setContent(`<!doctype html><style>html,body{margin:0;width:100%;height:100%}iframe{width:100%;height:100%;border:0;display:block}</style><script>window.previewState='loading';window.addEventListener('message',e=>{if(e.data?.type==='ui-library-preview')window.previewState=e.data.state})</script><iframe sandbox="allow-scripts" src="${base}${item.preview_url}"></iframe>`)
      await page.waitForFunction(() => window.previewState === 'ready', null, { timeout: 30000 })
      await page.waitForTimeout(2200)
      for (let step = 0; step < 12; step++) {
        await page.mouse.move(320 + Math.cos(step / 12 * Math.PI * 2) * 130, 200 + Math.sin(step / 12 * Math.PI * 2) * 55, { steps: 2 })
        await page.waitForTimeout(500)
      }
      if (errors.length) throw new Error(errors.join('\n'))
      const video = page.video()
      await context.close()
      const original = await video.path()
      const output = resolve(clips, `${item.id}.webm`)
      // Only the final six seconds: the loading phase is excluded.
      await run(ffmpeg, ['-hide_banner', '-loglevel', 'error', '-y', '-sseof', '-6', '-i', original, '-t', '6', '-an', '-c:v', 'libvpx', '-b:v', '450k', '-crf', '12', '-deadline', 'realtime', '-cpu-used', '4', output], { windowsHide: true })
      const result = { id: item.id, bytes: (await stat(output)).size, duration: 6, source: item.source_url, revision: item.revision }
      results.push(result)
      console.log(JSON.stringify(result))
    } finally { await context.close() }
  }
}
try { await Promise.all([worker(), worker(), worker()]) }
finally {
  await browser.close()
  await writeFile(resolve(root, '.ui-previews/clip-report.json'), JSON.stringify(results, null, 2))
}
