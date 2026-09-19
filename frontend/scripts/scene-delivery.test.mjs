// @vitest-environment node
import { test } from 'vitest'
import assert from 'node:assert/strict'
import { readFileSync, mkdtempSync, writeFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { webcrypto, createHash } from 'node:crypto'
import vm from 'node:vm'
import { prepareSceneDelivery } from './prepare-scene-delivery.mjs'

const source = readFileSync(new URL('./scene-delivery.js', import.meta.url), 'utf8')
const bytes = new TextEncoder().encode('verified scene bytes')
const spec = {bytes: bytes.length, sha256: createHash('sha256').update(bytes).digest('hex')}
const origin = 'https://aigcnews.cn'
function setup(fetcher, {cache = new Map(), cacheError = false, wasm = false} = {}) {
  const requests = [], events = []
  const target = new EventTarget()
  const window = {
    MEADOW_DELIVERY: {cdn: 'https://scene.aigcnews.cn/camp-scene/', assets: {[wasm ? 'index.wasm' : 'index.pck']: spec}},
    fetch: async (url, init) => { requests.push(url); return fetcher(url, init) },
    dispatchEvent: event => {events.push(event.detail); return target.dispatchEvent(event)},
  }
  const context = vm.createContext({window, location: {href: origin + '/camp-scene/index.html', origin},
    navigator: {}, crypto: webcrypto, caches: {open: async () => {
      if (cacheError) throw Error('disabled')
      return {match: async key => cache.get(key)?.clone(), put: async (key, val) => {cache.set(key, val)}, delete: async key => cache.delete(key)}
    }}, URL, Request, Response, Uint8Array, AbortController, CustomEvent, setTimeout, clearTimeout})
  vm.runInContext(source, context)
  return {window, requests, events, cache}
}

test('CDN bytes are verified, progress reported, and next page uses persistent cache', async () => {
  const first = setup(() => new Response(bytes))
  assert.deepEqual(new Uint8Array(await (await first.window.fetch('index.pck')).arrayBuffer()), bytes)
  assert.match(first.requests[0], new RegExp('^https://scene.aigcnews.cn/camp-scene/index.pck\\?v=' + spec.sha256))
  assert.equal(first.events.at(-1).loaded, bytes.length)
  const next = setup(() => { throw Error('must not download again') }, {cache: first.cache})
  await next.window.fetch('index.pck')
  assert.equal(next.requests.length, 0)
  assert.equal(next.events.at(-1).source, 'cache')
})

test('bad CDN digest falls back to origin and does not poison cache', async () => {
  const s = setup(url => new Response(url.startsWith(origin + '/') ? bytes : new Uint8Array(bytes.length)))
  await s.window.fetch('index.pck')
  assert.equal(s.requests.length, 2)
  assert.match(s.requests[1], /^https:\/\/aigcnews.cn\//)
  assert.equal(s.cache.size, 1)
})

test('corrupted cached resource is evicted and downloaded again', async () => {
  const cache = new Map([[origin + '/camp-scene/index.pck?v=' + spec.sha256, new Response('bad')]])
  const s = setup(() => new Response(bytes), {cache})
  await s.window.fetch('index.pck')
  assert.equal(s.requests.length, 1)
})

test('disabled cache does not block rendering', async () => {
  const s = setup(() => new Response(bytes), {cacheError: true})
  assert.equal((await s.window.fetch('index.pck')).status, 200)
})

test('abort cancels in-flight CDN request without origin retry or caching', async () => {
  let entered
  const started = new Promise(r => {entered = r})
  const s = setup((_url, {signal}) => new Promise((_resolve, reject) => {
    entered(); signal.addEventListener('abort', () => reject(signal.reason))
  }))
  const controller = new AbortController()
  const work = s.window.fetch('index.pck', {signal: controller.signal})
  await started
  controller.abort()
  await assert.rejects(work)
  assert.equal(s.requests.length, 1)
  assert.equal(s.cache.size, 0)
})

test('API, Range, and non-GET requests stay untouched', async () => {
  const s = setup(() => new Response('ok'))
  await s.window.fetch('/api/live')
  await s.window.fetch('index.pck', {headers: {Range: 'bytes=0-1'}})
  await s.window.fetch('index.pck', {method: 'POST'})
  assert.deepEqual(s.requests, ['/api/live', 'index.pck', 'index.pck'])
})

test('engine prewarm and actual startup share one transfer', async () => {
  const s = setup(() => new Response(bytes), {wasm: true})
  const response = await s.window.fetch('index.wasm')
  assert.equal(s.requests.length, 1)
  assert.equal(response.headers.get('content-type'), 'application/wasm')
})

test('adapter rejects unknown private bootstrap and leaves source untouched', () => {
  const dir = mkdtempSync(join(tmpdir(), 'scene-adapter-'))
  try {
    writeFileSync(join(dir, 'meadow-boot.js'), 'unreviewed')
    assert.throws(() => prepareSceneDelivery(dir), /Unreviewed/)
    assert.equal(readFileSync(join(dir, 'meadow-boot.js'), 'utf8'), 'unreviewed')
  } finally {rmSync(dir, {recursive: true})}
})

test('truncated bodies fail on both routes and are never persisted', async () => {
  const s = setup(() => new Response(bytes.slice(0, -1)))
  await assert.rejects(s.window.fetch('index.pck'), /资源下载不完整/)
  assert.equal(s.requests.length, 2)
  assert.equal(s.cache.size, 0)
})
