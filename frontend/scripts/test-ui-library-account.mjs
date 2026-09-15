import assert from 'node:assert/strict'
import { chromium } from 'playwright'
import { mkdir, readFile } from 'node:fs/promises'
import { resolve } from 'node:path'

const base = process.env.UI_LIBRARY_BASE_URL || 'http://127.0.0.1:18782'
const { items } = JSON.parse(await readFile('../mcp-go/internal/uicatalog/data/catalog.json', 'utf8'))
const browser = await chromium.launch({ channel: 'chrome', headless: true, ignoreDefaultArgs: ['--hide-scrollbars'] })
const context = await browser.newContext({ viewport: { width: 1920, height: 1080 } })
await context.grantPermissions(['clipboard-read', 'clipboard-write'], { origin: base })
const page = await context.newPage()
const errors = []
page.on('pageerror', error => errors.push(error.message))
let used = 0
let member = false
let unavailable = false
let copyRequests = 0
const liked = new Set()
const receipts = new Set()
const allowance = () => ({ limit: member ? null : 5, remaining: member ? null : Math.max(0, 5-used), used, resets_at: '2026-09-12T00:00:00+08:00' })
await page.route('**/api/**', async route => {
  const request = route.request()
  const url = new URL(request.url())
  const body = request.postDataJSON()
  let status = 200
  let data = { items: [], providers: [], features: {} }
  if (url.pathname === '/api/auth/me') data = { user_id: 1, email: 'ui-test@example.test', role: 'user', membership_tier: member ? 'member' : 'free' }
  if (url.pathname.endsWith('/engagement')) data = { items: items.map((item, index) => ({ template_id: item.id, likes: liked.has(item.id) ? 1 : 0, liked: liked.has(item.id), score: index === 1 && url.searchParams.get('period') === 'weekly' ? 8 : liked.has(item.id) ? 1 : 0 })) }
  if (url.pathname.endsWith('/copy-quota')) data = allowance()
  if (url.pathname.endsWith('/like')) {
    const id = url.pathname.split('/').at(-2)
    if (body.liked) liked.add(id); else liked.delete(id)
    data = { liked: body.liked }
  }
  if (url.pathname.endsWith('/copy')) {
    copyRequests++
    if (unavailable) { status = 503; data = {} }
    else if (!member && used >= 5 && !receipts.has(body.request_id)) { status = 429; data = { detail: { code: 'ui_copy_limit' } } }
    else {
      if (!receipts.has(body.request_id)) { receipts.add(body.request_id); used++ }
      data = allowance()
    }
  }
  await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(data) })
})
const first = () => page.locator(`[data-template-id="${items[0].id}"]`)
const clipboard = () => page.evaluate(() => navigator.clipboard.readText())
const reload = async () => {
  await page.goto(base + '/ui-library')
  await first().waitFor()
  await page.waitForFunction(() => !document.querySelector('.ui-library__quota')?.textContent.includes('正在确认'))
}
try {
  await reload()
  await first().locator('.ui-library__copy-source').click()
  await page.locator('input[type=password]').first().waitFor({ state: 'visible' })
  assert.equal(copyRequests, 0, 'anonymous copy must open login before consuming')
  await page.evaluate(() => localStorage.setItem('auth_token', 'ui-browser-test-token'))
  await reload()
  await first().locator('.ui-library__like').click()
  await page.waitForFunction(() => document.querySelector('.ui-library__like')?.getAttribute('aria-pressed') === 'true')
  await page.getByRole('button', { name: '我的喜欢', exact: true }).click()
  await page.waitForFunction(() => document.querySelectorAll('.ui-library__card').length === 1)
  await page.getByRole('button', { name: '周榜', exact: true }).click()
  await page.waitForFunction(id => document.querySelector('.ui-library__card')?.getAttribute('data-template-id') === id, items[1].id)
  await page.getByRole('button', { name: '月榜', exact: true }).click()
  await page.waitForURL('**/ui-library?rank=monthly')
  await page.getByRole('button', { name: '今日热榜', exact: true }).click()
  await page.getByRole('button', { name: '全部', exact: true }).click()
  for (let i = 0; i < 5; i++) {
    await first().locator(i % 2 ? '.ui-library__copy-prompt' : '.ui-library__copy-source').click()
    await page.waitForFunction(n => document.querySelector('.ui-library__quota')?.textContent.includes(`剩余 ${n} / 5`), 4-i)
    await page.waitForFunction(() => !document.querySelector('.ui-library__copy-source')?.disabled)
  }
  const previous = await clipboard()
  await first().locator('.ui-library__copy-source').click()
  await page.getByText('今日 5 次复制额度已用完，明日恢复；VIP 不限次数。', { exact: true }).waitFor()
  assert.equal(await clipboard(), previous)
  await reload()
  assert.ok((await page.locator('.ui-library__quota').textContent()).includes('剩余 0 / 5'))
  member = true
  await reload()
  await first().locator('.ui-library__copy-prompt').click()
  await page.waitForFunction(() => document.querySelector('.ui-library__card-feedback')?.textContent.includes('提示词已复制'))
  assert.ok(used > 5)
  await first().locator('.ui-library__card-title').click()
  await page.locator('.ui-detail__copy-source:not(:disabled)').waitFor()
  await page.locator('.ui-detail__copy-source').click()
  await page.locator('.ui-detail__feedback').waitFor()
  assert.equal(await page.locator('.ui-detail__feedback').textContent(), '已复制')
  await page.keyboard.press('Escape')
  unavailable = true
  const beforeFailure = await clipboard()
  await first().locator('.ui-library__copy-source').click()
  await page.getByText('暂时无法确认复制额度，请重试。', { exact: true }).waitFor()
  assert.equal(await clipboard(), beforeFailure, 'quota service failure must not copy')
  unavailable = false
  await page.evaluate(() => {
    const original = navigator.clipboard.writeText.bind(navigator.clipboard)
    navigator.clipboard.writeText = async value => { navigator.clipboard.writeText = original; throw new Error('test clipboard denial') }
  })
  await first().locator('.ui-library__copy-source').click()
  await page.getByText('剪贴板写入失败，请重试；本次重试不重复扣额度。', { exact: true }).waitFor()
  const afterFailure = used
  await first().locator('.ui-library__copy-source').click()
  await page.waitForFunction(() => document.querySelector('.ui-library__card-feedback')?.textContent.includes('完整源码已复制'))
  assert.equal(used, afterFailure, 'clipboard retry reuses its server receipt')
  await mkdir('../test-results/ui-library', { recursive: true })
  await page.screenshot({ path: resolve('../test-results/ui-library/gallery-likes-rankings.png') })
  assert.deepEqual(errors, [])
  console.log('Browser account checks passed (mock API): login, likes, rolling tabs, shared copy quota, reload, VIP, dialog, fail-closed and idempotent retry.')
} finally { await browser.close() }
