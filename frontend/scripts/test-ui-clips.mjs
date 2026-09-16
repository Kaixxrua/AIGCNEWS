import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { request as httpRequest } from 'node:http'
import { request as httpsRequest } from 'node:https'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const data = resolve(root, '../mcp-go/internal/uicatalog/data')
const base = process.env.UI_LIBRARY_BASE_URL || 'http://127.0.0.1:18782'
const { items } = JSON.parse(await readFile(resolve(data, 'catalog.json'), 'utf8'))
function request(path, headers = {}, method = 'GET') {
  return new Promise((resolve, reject) => {
    const url = new URL(path, base)
    const send = url.protocol === 'https:' ? httpsRequest : httpRequest
    const req = send(url, { method, headers, rejectUnauthorized: !process.env.UI_LIBRARY_INSECURE_TLS }, response => {
      const chunks = []
      response.on('data', chunk => chunks.push(chunk))
      response.on('end', () => resolve({ status: response.statusCode, headers: response.headers, body: Buffer.concat(chunks) }))
    })
    req.on('error', reject)
    req.end()
  })
}
for (const item of items) {
  const response = await request(item.clip_url)
  assert.equal(response.status, 200)
  assert.ok(response.headers['content-type'].startsWith('video/webm'))
  assert.deepEqual(response.body, await readFile(resolve(data, 'clips', item.id + '.webm')))
}
const item = items[0]
const original = await readFile(resolve(data, 'clips', item.id + '.webm'))
const head = await request(item.clip_url, {}, 'HEAD')
assert.equal(head.status, 200)
assert.equal(Number(head.headers['content-length']), original.length)
assert.equal(head.body.length, 0)
for (const [range, content] of [['bytes=0-31', original.subarray(0, 32)], ['bytes=-32', original.subarray(-32)]]) {
  const response = await request(item.clip_url, { Range: range })
  assert.equal(response.status, 206)
  assert.ok(response.headers['content-range'].endsWith('/' + original.length))
  assert.deepEqual(response.body, content)
}
assert.equal((await request(item.clip_url, { Range: 'bytes=' + original.length + '-' })).status, 416)
assert.equal((await request('/ui-library/clips/missing.webm')).status, 404)
console.log('All 30 original clips served correctly; MIME, HEAD, byte ranges, 416 and missing-file 404 passed.')
