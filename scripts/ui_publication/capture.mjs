// Generated previews run in disposable browser contexts with outbound requests blocked.
import { readFile } from 'node:fs/promises'
import { resolve } from 'node:path'
import { captureUiMedia } from './ui-media-capture.mjs'

const data = resolve('../mcp-go/internal/uicatalog/data')
const ids = JSON.parse(await readFile(process.env.UI_PREVIEW_IDS_FILE, 'utf8'))
const { items } = JSON.parse(await readFile(resolve(data, 'catalog.json'), 'utf8'))
const selected = items.filter(item => ids.includes(item.id))
const results = await captureUiMedia({ items: selected, data, base: process.env.UI_LIBRARY_BASE_URL,
  reportFile: process.env.UI_RENDER_REPORT_FILE, ffmpeg: process.env.FFMPEG_PATH || 'ffmpeg.exe',
  channel: 'chrome', concurrency: Number(process.env.UI_MEDIA_WORKERS || 3) })
console.log(JSON.stringify({ rendered: results.length, failed: results.filter(row => row.state !== 'ready' || row.errors.length).length }))
