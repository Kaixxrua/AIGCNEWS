import { readdirSync, readFileSync, statSync, existsSync, writeFileSync } from 'node:fs'
import { createHash } from 'node:crypto'
import { resolve, relative } from 'node:path'
import { fileURLToPath } from 'node:url'
import type { Plugin } from 'vite'
import type { UiTemplate } from '../src/features/ui-library/catalog'
import { previewFiles } from './uiPreviewManifest'

const root = fileURLToPath(new URL('../', import.meta.url))
const roots = [
  { folder: resolve(root, '../mcp-go/internal/uicatalog/data'), prefix: '' },
  // Only deploy runtime previews, never local screenshots, reports or test fixtures.
  { folder: resolve(root, '.ui-previews/previews'), prefix: 'previews/' },
]
const mime: Record<string, string> = { json: 'application/json', html: 'text/html', js: 'text/javascript', mjs: 'text/javascript', css: 'text/css', png: 'image/png', jpg: 'image/jpeg', jpeg: 'image/jpeg', webp: 'image/webp', svg: 'image/svg+xml', gif: 'image/gif', ico: 'image/x-icon', woff: 'font/woff', woff2: 'font/woff2', ttf: 'font/ttf', otf: 'font/otf', webm: 'video/webm', mp4: 'video/mp4', mp3: 'audio/mpeg', wasm: 'application/wasm', zip: 'application/zip' }
function filesIn(folder: string): string[] {
  if (!existsSync(folder)) return []
  return readdirSync(folder).filter(name => !name.startsWith('.')).flatMap(name => {
    const path = resolve(folder, name)
    return statSync(path).isDirectory() ? filesIn(path) : [path]
  })
}
export function uiLibraryAssets(): Plugin {
  const assets = new Map<string, string>()
  let productionBuild = false
  const collect = () => {
    assets.clear()
    const data = roots[0]!.folder
    const { items } = JSON.parse(readFileSync(resolve(data, 'catalog.json'), 'utf8')) as { items: UiTemplate[] }
    const allowed = new Set(['catalog.json', 'upstreams.json'])
    const evidence = new Set<string>()
    for (const item of items) {
      for (const [name] of previewFiles(item)) allowed.add(name)
      for (const file of [...item.files, ...item.notices, ...item.assets]) allowed.add(file.path)
      for (const url of [item.poster_url, item.clip_url]) if (url) allowed.add(url.replace('/ui-library/', ''))
      if (item.rights_evidence_url) evidence.add(item.rights_evidence_url.replace('/ui-library/', ''))
      if (item.editorial?.status === 'approved') {
        const reviewPath = item.editorial.evidence.replace('/ui-library/', '')
        const review = JSON.parse(readFileSync(resolve(data, reviewPath), 'utf8')) as {
          preview_files?: Record<string, string>
        }
        allowed.add(item.preview_url.replace('/ui-library/', ''))
        for (const name of Object.keys(review.preview_files ?? {})) allowed.add(`previews/${name}`)
      }
    }
    for (const filename of evidence) {
      allowed.add(filename)
      const dir = resolve(data, filename, '..')
      for (const path of filesIn(dir)) allowed.add(relative(data, path).replaceAll('\\', '/'))
    }
    for (const name of allowed) assets.set('/ui-library/' + name, resolve(data, name))
    for (const path of filesIn(roots[1]!.folder)) {
      const name = relative(roots[1]!.folder, path).replaceAll('\\', '/')
      if (items.some(item => name.startsWith(item.id + '.'))) assets.set('/ui-library/previews/' + name, path)
    }
  }
  return {
    name: 'ui-library-assets',
    configResolved(config) { productionBuild = config.command === 'build' },
    buildStart() {
      collect()
      if (!productionBuild) return
      const data = roots[0]!.folder
      const { items } = JSON.parse(readFileSync(resolve(data, 'catalog.json'), 'utf8')) as { items: UiTemplate[] }
      const proofs = new Map<string, { revision: string; license: string; source_files: Record<string, string> }>()
      const checked = new Map<string, string>()
      const hash = (path: string) => {
        if (!checked.has(path)) checked.set(path, createHash('sha256').update(readFileSync(path)).digest('hex'))
        return checked.get(path)!
      }
      for (const item of items) {
        for (const [name, digest] of previewFiles(item)) if (hash(resolve(data, name)) !== digest) throw new Error('Preview integrity failure: ' + name)
        const expected = '/ui-library/assets/' + item.provider_id + '/evidence/' + item.revision + '/manifest.json'
        if (item.rights_evidence_url !== expected) throw new Error('Missing rights evidence: ' + item.id)
        let proof = proofs.get(expected)
        if (!proof) {
          const path = assets.get(expected)!
          const record = JSON.parse(readFileSync(path, 'utf8'))
          if (!record.license_grants?.includes('commercial-use') || !record.license_grants?.includes('redistribution') || !record.screenshot_sha256) throw new Error('Incomplete rights evidence: ' + item.id)
          for (const resource of [...record.resources, { name: record.screenshot, sha256: record.screenshot_sha256 }]) {
            if (resource.name.includes('/') || resource.name.includes('\\') || resource.name === '..') throw new Error('Invalid evidence path')
            if (createHash('sha256').update(readFileSync(resolve(path, '..', resource.name))).digest('hex') !== resource.sha256) throw new Error('Evidence integrity failure')
          }
          proof = record
          proofs.set(expected, proof!)
        }
        if (proof!.revision !== item.revision || proof!.license !== item.license) throw new Error('Rights evidence mismatch')
        for (const file of [...item.files, ...item.notices, ...item.assets]) {
          if (hash(resolve(data, file.path)) !== file.sha256) throw new Error('Source integrity failure: ' + file.path)
        }
        for (const file of item.files) if (proof!.source_files[file.path] !== file.sha256) throw new Error('Source not covered by rights evidence: ' + file.path)
        for (const url of [item.preview_url, item.poster_url, item.clip_url].filter(Boolean)) if (!assets.has(url) || !existsSync(assets.get(url)!)) throw new Error('Missing preview asset: ' + url)
        if (item.editorial) {
          const review = item.editorial
          const expectedReview = expected.replace('manifest.json', 'review-' + item.id + '.json')
          if (review.status !== 'approved' || review.revision !== item.revision || review.source_sha256 !== item.files[0]?.sha256 || review.evidence !== expectedReview) throw new Error('Stale visual review: ' + item.id)
          const record = JSON.parse(readFileSync(assets.get(review.evidence)!, 'utf8'))
          if (record.id !== item.id || record.revision !== item.revision || item.files.some(file => record.source_files[file.path] !== file.sha256)) throw new Error('Visual review source mismatch: ' + item.id)
          for (const [name, digest] of [[record.screenshot, record.screenshot_sha256], ...(record.dark_screenshot ? [[record.dark_screenshot, record.dark_screenshot_sha256]] : [])]) {
            if (typeof name !== 'string' || /[/\\]/.test(name) || name === '..' || createHash('sha256').update(readFileSync(resolve(data, review.evidence.replace('/ui-library/', ''), '..', name))).digest('hex') !== digest) throw new Error('Visual review evidence mismatch: ' + item.id)
          }
          if (createHash('sha256').update(readFileSync(assets.get(item.preview_url)!)).digest('hex') !== record.preview_html_sha256) throw new Error('Preview changed after visual review: ' + item.id)
          for (const [filename, digest] of Object.entries(record.preview_files ?? {})) {
            const path = assets.get('/ui-library/previews/' + filename)
            const pinned = item.preview_files?.['previews/' + filename] === digest
            if (!path || (!filename.startsWith(item.id + '.') && !pinned) || hash(path) !== digest) throw new Error('Reviewed preview file changed: ' + item.id)
          }
        }
      }
    },
    configureServer(server) {
      collect()
      server.middlewares.use((req, res, next) => {
        let key: string
        try { key = decodeURIComponent(req.url?.split('?')[0] ?? '') } catch { res.statusCode = 400; res.end(); return }
        if (!/^\/ui-library\/(?:catalog\.json|upstreams\.json|previews\/|posters\/|clips\/|sources\/|licenses\/|assets\/)/.test(key)) return next()
        if (req.method !== 'GET' && req.method !== 'HEAD') { res.statusCode = 405; res.setHeader('Allow', 'GET, HEAD'); res.end(); return }
        let path = assets.get(key)
        if (!path) { collect(); path = assets.get(key) }
        if (!path) { res.statusCode = 404; res.end(); return }
        const extension = /^\/ui-library\/(sources|licenses)\//.test(key) ? '' : path.split('.').pop() ?? ''
        res.setHeader('Content-Type', `${mime[extension] ?? 'text/plain'}${extension === 'webm' ? '' : '; charset=utf-8'}`)
        res.setHeader('X-Content-Type-Options', 'nosniff')
        if (extension === 'webm') {
          const size = statSync(path).size
          res.setHeader('Accept-Ranges', 'bytes')
          if (req.headers.range) {
            const match = /^bytes=(\d*)-(\d*)$/.exec(req.headers.range)
            const start = match?.[1] ? Number(match[1]) : Math.max(0, size - Number(match?.[2]))
            const end = match?.[1] && match[2] ? Math.min(Number(match[2]), size - 1) : size - 1
            if (!match || (!match[1] && !match[2]) || !Number.isSafeInteger(start) || !Number.isSafeInteger(end) || start > end || start >= size) {
              res.statusCode = 416; res.setHeader('Content-Range', `bytes */${size}`); res.end(); return
            }
            res.statusCode = 206
            res.setHeader('Content-Range', `bytes ${start}-${end}/${size}`)
            res.setHeader('Content-Length', end - start + 1)
            res.end(req.method === 'HEAD' ? undefined : readFileSync(path).subarray(start, end + 1)); return
          }
          res.setHeader('Content-Length', size)
        }
        res.end(req.method === 'HEAD' ? undefined : readFileSync(path))
      })
    },
    generateBundle() {
      // Release packagers can stream the already validated library directly into
      // an archive, avoiding tens of thousands of temporary Windows file writes.
      if (process.env.UI_LIBRARY_ASSET_MANIFEST) {
        writeFileSync(process.env.UI_LIBRARY_ASSET_MANIFEST, JSON.stringify(Object.fromEntries(assets)))
        return
      }
      for (const [key, path] of assets) this.emitFile({ type: 'asset', fileName: key.slice(1), source: readFileSync(path) })
    },
  }
}
