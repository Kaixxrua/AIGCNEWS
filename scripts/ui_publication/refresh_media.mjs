// Node side of scripts/ui_publication/refresh.py. Copied into the staged
// frontend/scripts directory so it resolves the frontend's playwright install.
//
//   media:    capture poster + clip in a network-blocked page, then measure the
//             poster's gray-level spread so blank renders can be held.
//   evidence: screenshot the pinned GitHub license page for rights evidence.
import { chromium } from 'playwright'
import { execFile } from 'node:child_process'
import { createHash } from 'node:crypto'
import { readFile, writeFile } from 'node:fs/promises'
import { resolve } from 'node:path'
import { promisify } from 'node:util'
import { captureUiMedia } from './ui-media-capture.mjs'

const run = promisify(execFile)
const digest = raw => createHash('sha256').update(raw).digest('hex')
const LICENSE_TEXT = { MIT: 'MIT License', 'Apache-2.0': 'Apache License', ISC: 'ISC License' }

async function posterStddev(ffmpeg, poster) {
  const { stdout } = await run(ffmpeg, ['-hide_banner', '-loglevel', 'error', '-i', poster, '-vf', 'scale=160:100',
    '-f', 'rawvideo', '-pix_fmt', 'gray', 'pipe:1'], { encoding: 'buffer', maxBuffer: 1 << 20 })
  if (!stdout.length) return 0
  let sum = 0
  for (const value of stdout) sum += value
  const mean = sum / stdout.length
  let variance = 0
  for (const value of stdout) variance += (value - mean) ** 2
  return Math.sqrt(variance / stdout.length)
}

async function media(job) {
  const rows = await captureUiMedia({ items: job.items, data: job.data, base: job.base, ffmpeg: job.ffmpeg,
    concurrency: job.workers })
  for (const row of rows) {
    if (row.state !== 'ready') continue
    const item = job.items.find(candidate => candidate.id === row.id)
    const poster = resolve(job.data, item.poster_url.slice('/ui-library/'.length))
    row.poster_stddev = await posterStddev(job.ffmpeg, poster).catch(() => 0)
  }
  return rows
}

async function evidence(job) {
  const proxy = process.env.HTTPS_PROXY || process.env.https_proxy
  const browser = await chromium.launch({ headless: true, ...(proxy ? { proxy: { server: proxy } } : {}) })
  const rows = []
  try {
    for (const page of job.pages) {
      const row = { manifest: page.manifest }
      try {
        if (!/^https:\/\/github\.com\/[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+\/blob\/[0-9a-f]{40}\//.test(page.url)) throw new Error('unexpected license page URL')
        const text = LICENSE_TEXT[page.license]
        if (!text) throw new Error('unsupported license ' + page.license)
        const context = await browser.newContext({ viewport: { width: 1280, height: 900 }, locale: 'en-US' })
        try {
          const tab = await context.newPage()
          await tab.goto(page.url, { waitUntil: 'domcontentloaded', timeout: 60_000 })
          await tab.getByText(text, { exact: false }).first().waitFor({ timeout: 60_000 })
          await tab.waitForTimeout(800)
          await tab.screenshot({ path: page.out, fullPage: true })
        } finally {
          await context.close()
        }
        row.sha256 = digest(await readFile(page.out))
      } catch (error) {
        row.error = error instanceof Error ? error.message.slice(0, 300) : String(error)
      }
      rows.push(row)
    }
  } finally {
    await browser.close()
  }
  return rows
}

const job = JSON.parse(await readFile(process.argv[2], 'utf8'))
const rows = job.mode === 'media' ? await media(job) : job.mode === 'evidence' ? await evidence(job) : null
if (!rows) throw new Error('unknown refresh job mode')
await writeFile(job.report, JSON.stringify(rows, null, 2) + '\n')
