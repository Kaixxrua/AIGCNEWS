// Backfill real component previews as compact, streamable MP4 + WebP media.
import { readFile, rename, writeFile } from 'node:fs/promises'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { captureUiMedia } from './ui-media-capture.mjs'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const data = resolve(process.env.UI_LIBRARY_DATA_DIR || resolve(root, '../mcp-go/internal/uicatalog/data'))
const base = process.env.UI_LIBRARY_BASE_URL || 'http://127.0.0.1:18782'
const catalogPath = resolve(data, 'catalog.json')
const catalog = JSON.parse(await readFile(catalogPath, 'utf8'))
const prefixes = process.argv.slice(2).filter(value => !value.startsWith('--'))
const selected = catalog.items.filter(item => !prefixes.length || prefixes.some(prefix => item.id.startsWith(prefix)))
const items = selected.map(item => {
  const version = item.revision.slice(0, 12)
  return { ...item, fallback_poster_url: item.poster_url, poster_url: `/ui-library/posters/${item.id}-${version}.webp`, clip_url: `/ui-library/clips/${item.id}-${version}.mp4` }
})
const reportFile = resolve(root, '.ui-previews/clip-report.json')
const results = await captureUiMedia({ items, data, base, reportFile,
  ffmpeg: process.env.FFMPEG_PATH || 'ffmpeg', channel: process.env.PLAYWRIGHT_CHANNEL,
  executablePath: process.env.PLAYWRIGHT_EXECUTABLE_PATH, concurrency: Number(process.env.UI_MEDIA_WORKERS || 3) })
const passed = new Set(results.filter(row => row.state === 'ready' && !row.errors.length).map(row => row.id))
if (process.argv.includes('--write-catalog')) {
  const updates = new Map(items.filter(item => passed.has(item.id)).map(item => [item.id, item]))
  catalog.items = catalog.items.map(item => updates.has(item.id) ? { ...item, poster_url: updates.get(item.id).poster_url, clip_url: updates.get(item.id).clip_url } : item)
  const temporary = catalogPath + '.next'
  await writeFile(temporary, JSON.stringify(catalog, null, 2) + '\n')
  await rename(temporary, catalogPath)
}
console.log(JSON.stringify({ requested: items.length, rendered: passed.size, failed: items.length - passed.size, report: reportFile }))
if (passed.size !== items.length) process.exitCode = 1
