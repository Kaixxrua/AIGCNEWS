import { chromium } from 'playwright'
import { execFile } from 'node:child_process'
import { mkdtemp, mkdir, readFile, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { basename, resolve } from 'node:path'
import { promisify } from 'node:util'
import { createHash } from 'node:crypto'

const run = promisify(execFile)
const digest = raw => createHash('sha256').update(raw).digest('hex')

function mediaPath(data, url, extension) {
  if (!url.startsWith('/ui-library/') || !url.endsWith(extension)) throw new Error(`Invalid media URL: ${url}`)
  const relative = url.slice('/ui-library/'.length)
  if (relative.split('/').some(part => !part || part === '.' || part === '..')) throw new Error(`Unsafe media URL: ${url}`)
  return resolve(data, relative)
}

async function gpuFallback(item, data, ffmpeg, errors) {
  if (!item.fallback_poster_url || !errors.some(value => /GPU|Instance reference/.test(value))) return undefined
  const source = mediaPath(data, item.fallback_poster_url, item.fallback_poster_url.endsWith('.webp') ? '.webp' : '.png')
  const poster = mediaPath(data, item.poster_url, '.webp')
  const clip = mediaPath(data, item.clip_url, '.mp4')
  await run(ffmpeg, ['-hide_banner', '-loglevel', 'error', '-y', '-i', source, '-frames:v', '1', '-c:v', 'libwebp', '-q:v', '72', '-compression_level', '6', '-preset', 'picture', poster], { windowsHide: true })
  await run(ffmpeg, ['-hide_banner', '-loglevel', 'error', '-y', '-loop', '1', '-i', source, '-t', '6', '-an',
    '-vf', 'scale=640:400:force_original_aspect_ratio=decrease,pad=640:400:(ow-iw)/2:(oh-ih)/2,fps=24',
    '-c:v', 'libx264', '-preset', 'medium', '-crf', '28', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', clip], { windowsHide: true })
  const posterRaw = await readFile(poster)
  const clipRaw = await readFile(clip)
  return { id: item.id, state: 'ready', errors: [], warnings: ['webgpu_static_fallback'], poster_bytes: posterRaw.length,
    poster_sha256: digest(posterRaw), clip_bytes: clipRaw.length, clip_sha256: digest(clipRaw), duration: 6 }
}

export async function captureUiMedia({ items, data, base, reportFile, ffmpeg = 'ffmpeg', channel, executablePath, concurrency = 3 }) {
  if (!Number.isInteger(concurrency) || concurrency < 1 || concurrency > 6) throw new Error('UI media concurrency must be between 1 and 6')
  const recordings = await mkdtemp(resolve(tmpdir(), 'aigcnews-ui-media-'))
  const launch = { headless: true, args: ['--enable-unsafe-swiftshader', '--enable-unsafe-webgpu'] }
  if (channel) launch.channel = channel
  if (executablePath) launch.executablePath = executablePath
  const browser = await chromium.launch(launch)
  const pending = [...items]
  const results = []
  async function worker() {
    while (pending.length) {
      const item = pending.shift()
      const errors = []
      let state = 'error'
      let context
      try {
        if (!/^[a-z0-9][a-z0-9._-]{0,240}$/.test(item.id)) throw new Error('Invalid template ID')
        const poster = mediaPath(data, item.poster_url, '.webp')
        const clip = mediaPath(data, item.clip_url, '.mp4')
        await mkdir(resolve(poster, '..'), { recursive: true })
        await mkdir(resolve(clip, '..'), { recursive: true })
        context = await browser.newContext({ viewport: { width: 640, height: 400 }, deviceScaleFactor: 1,
          recordVideo: { dir: recordings, size: { width: 640, height: 400 } } })
        const page = await context.newPage()
        page.on('pageerror', error => errors.push(error.message))
        page.on('console', message => {
          const value = message.text()
          // Some reviewed previews intentionally keep unavailable demo images
          // behind CSP or omit optional gallery thumbnails. The component can
          // still report ready and produce a complete primary composition.
          const optionalAsset = /Failed to load resource: the server responded with a status of 404|Loading the image .* violates the following Content Security Policy directive/.test(value)
          if (message.type() === 'error' && !optionalAsset) errors.push(value)
        })
        await page.route('**/*', route => route.request().url().startsWith(base + '/') ? route.continue() : route.abort())
        await page.addInitScript(() => {
          window.__uiCaptureState = 'loading'
          window.addEventListener('message', event => {
            if (event.source === window && event.data?.type === 'ui-library-preview') window.__uiCaptureState = event.data.state
          })
        })
        await page.goto(base + item.preview_url, { waitUntil: 'domcontentloaded', timeout: 30_000 })
        await page.waitForFunction(() => window.__uiCaptureState === 'ready', null, { timeout: 30_000 })
        await page.waitForTimeout(700)
        const png = resolve(recordings, `${basename(item.id)}.png`)
        await page.screenshot({ path: png, type: 'png' })
        await run(ffmpeg, ['-hide_banner', '-loglevel', 'error', '-y', '-i', png, '-frames:v', '1', '-c:v', 'libwebp', '-q:v', '72', '-compression_level', '6', '-preset', 'picture', poster], { windowsHide: true })
        for (let step = 0; step < 12; step++) {
          await page.mouse.move(320 + Math.cos(step / 12 * Math.PI * 2) * 130, 200 + Math.sin(step / 12 * Math.PI * 2) * 55, { steps: 2 })
          await page.waitForTimeout(500)
        }
        if (errors.length) throw new Error(errors.join('\n'))
        const recording = page.video()
        await context.close()
        context = undefined
        const source = await recording.path()
        await run(ffmpeg, ['-hide_banner', '-loglevel', 'error', '-y', '-sseof', '-6', '-i', source, '-t', '6', '-an',
          '-vf', 'fps=24,scale=640:400:force_original_aspect_ratio=decrease,pad=640:400:(ow-iw)/2:(oh-ih)/2',
          '-c:v', 'libx264', '-preset', 'medium', '-crf', '28', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', clip], { windowsHide: true })
        const posterRaw = await readFile(poster)
        const clipRaw = await readFile(clip)
        if (posterRaw.length < 512 || clipRaw.length < 2_048 || clipRaw.length > 3 * 1024 * 1024) throw new Error('Generated media size is outside limits')
        state = 'ready'
        const result = { id: item.id, state, errors: [], poster_bytes: posterRaw.length, poster_sha256: digest(posterRaw),
          clip_bytes: clipRaw.length, clip_sha256: digest(clipRaw), duration: 6 }
        results.push(result)
        console.log(JSON.stringify({ media_capture: result }))
      } catch (error) {
        errors.push(error instanceof Error ? error.message : String(error))
        const fallback = await gpuFallback(item, data, ffmpeg, errors).catch(() => undefined)
        if (fallback) {
          results.push(fallback)
          console.log(JSON.stringify({ media_capture: fallback }))
          continue
        }
        const result = { id: item.id, state, errors }
        results.push(result)
        console.log(JSON.stringify({ media_capture: result }))
      } finally {
        if (context) await context.close().catch(() => undefined)
      }
    }
  }
  try {
    await Promise.all(Array.from({ length: concurrency }, worker))
  } finally {
    await browser.close()
    await rm(recordings, { recursive: true, force: true })
    if (reportFile) await writeFile(reportFile, JSON.stringify(results, null, 2) + '\n')
  }
  return results
}
