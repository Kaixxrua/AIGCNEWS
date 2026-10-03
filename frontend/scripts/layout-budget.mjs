// 桌面版面预算：内页在四档桌面宽度 × 中英文下的布局偏移（CLS）、横向溢出、首屏完整条目数，
// 列表页再按一遍 j / k / ? / Esc。超预算的组合逐条列出，非零退出。说明见 docs/layout-budget.md。
//
//   VITE_API_PROXY_TARGET=https://aigcnews.cn npx vite preview --port 4173   # 先 vite build，另开终端
//   npm run check:layout                                                       # 默认测 http://127.0.0.1:4173
//
// 只读：/api 下除 GET 以外的请求一律拦掉，实时事件流也不连，所以可以直接对着生产跑。
// LAYOUT_BASE_URL     被测站点，默认 http://127.0.0.1:4173
// LAYOUT_RESOLVE      把域名钉到一个边缘，如 aigcnews.cn=<边缘 IP>；钉了就不走代理
// LAYOUT_PAGES        只测这几页，逗号分隔，如 report,projects
// LAYOUT_CONCURRENCY  同时开几页，默认 3
// LAYOUT_REPORT_DIR   超预算的组合截一张首屏存到这里
// CHROME_PATH         换用指定的 Chromium，缺省用 Playwright 自带的
import { chromium } from 'playwright'
import { mkdir } from 'node:fs/promises'

const SIZES = [[1024, 640], [1350, 657], [1536, 730], [1920, 960]]
const LOCALES = ['zh-CN', 'en-US']
const CLS_LIMIT = 0.1
const SETTLE_MS = 3000

// whole：首屏里上下沿都露出来、没被报头页脚盖住的条目，按宽度给 [中文, 英文] 两个下限。数据天天变的页
// 留了余量，简报钉在一期上。fits：这块要整个落在首屏里（会员对比表、MCP 的接入命令）。keys：走一遍列表键盘流。
const PAGES = [
  { name: 'report', path: '/report?date=2026-10-03', ready: '.report-broadsheet__item', whole: ['.report-broadsheet__item', { 1024: [0, 0], 1350: [2, 0], 1536: [2, 2], 1920: [7, 5] }], keys: true },
  { name: 'projects', path: '/projects', ready: '.project-row', whole: ['.project-row', { 1024: [2, 2], 1350: [4, 2], 1536: [5, 4], 1920: [8, 8] }], keys: true },
  { name: 'x', path: '/x', ready: '.tweet-card', whole: ['.tweet-card', { 1024: [2, 2], 1350: [3, 3], 1536: [4, 4], 1920: [6, 6] }], keys: true },
  { name: 'ui-library', path: '/ui-library', ready: '.ui-library__card', whole: ['.ui-library__card', { 1024: [3, 3], 1350: [10, 10], 1536: [12, 12], 1920: [21, 21] }] },
  { name: 'membership', path: '/membership', ready: '.membership-card--compare', fits: ['.membership-card--compare', 1350] },
  { name: 'mcp', path: '/mcp', ready: '.command-preview', fits: ['.command-preview', 1024] },
  { name: 'websites', path: '/projects?source=website', ready: 'h1' },
  { name: 'dsh', path: '/dsh', ready: 'h1' },
  { name: 'subscriptions', path: '/subscriptions', ready: 'h1' },
]

const env = process.env
const base = (env.LAYOUT_BASE_URL || 'http://127.0.0.1:4173').replace(/\/$/, '')
const only = env.LAYOUT_PAGES ? new Set(env.LAYOUT_PAGES.split(',').map((name) => name.trim())) : null
const reportDir = env.LAYOUT_REPORT_DIR
if (reportDir) await mkdir(reportDir, { recursive: true })

const args = []
if (env.LAYOUT_RESOLVE) {
  const [host, ip] = env.LAYOUT_RESOLVE.split('=')
  args.push(`--host-resolver-rules=MAP ${host} ${ip}`, '--no-proxy-server')
}
const browser = await chromium.launch({ headless: true, executablePath: env.CHROME_PATH || undefined, args })

// 首屏完整条目：整块在视口里，上下沿各取一点做命中测试，被报头、页脚、浮层或滚动容器裁掉的不算。
function countWhole(selector) {
  let count = 0
  for (const el of document.querySelectorAll(selector)) {
    const box = el.getBoundingClientRect()
    if (!box.width || !box.height || box.top < 0 || box.left < 0 || box.bottom > innerHeight || box.right > innerWidth) continue
    const x = box.left + box.width / 2
    const sees = (y) => {
      const hit = document.elementFromPoint(x, y)
      return !!hit && el.contains(hit)
    }
    if (sees(box.top + 2) && sees(box.bottom - 2)) count++
  }
  return count
}

function fitsInView(selector) {
  const box = document.querySelector(selector)?.getBoundingClientRect()
  return !!box && box.top >= 0 && box.bottom <= innerHeight
}

function listState() {
  const active = document.activeElement
  const box = active?.getBoundingClientRect()
  return {
    key: active?.dataset?.listKey ?? null,
    inView: !!box && box.bottom > 0 && box.top < innerHeight,
    cursors: document.querySelectorAll('[data-list-key].is-cursor').length,
    sheet: (document.querySelector('.list-keys-sheet')?.getClientRects().length ?? 0) > 0,
  }
}

// j 亮出视野里的条目并把焦点放上去，再 j 换到另一条，k 回来；? 开快捷键表、Esc 关；再 Esc 收起光标。
async function checkKeys(page) {
  const problems = []
  const press = async (key) => {
    await page.keyboard.press(key)
    await page.waitForTimeout(350)
    return page.evaluate(listState)
  }
  await page.evaluate(() => document.activeElement instanceof HTMLElement && document.activeElement.blur())
  const first = await press('j')
  if (!first.key || !first.inView || first.cursors !== 1) problems.push(`j 没把光标亮在视野里的条目上（${JSON.stringify(first)}）`)
  const second = await press('j')
  if (!second.key || second.key === first.key || !second.inView) problems.push('第二下 j 没走到下一条')
  const back = await press('k')
  if (back.key !== first.key) problems.push('k 没回到上一条')
  if (!(await press('?')).sheet) problems.push('? 没打开快捷键表')
  if ((await press('Escape')).sheet) problems.push('Esc 没关掉快捷键表')
  if ((await press('Escape')).cursors !== 0) problems.push('Esc 没收起光标')
  return problems
}

async function measure(spec, [width, height], locale) {
  const context = await browser.newContext({ viewport: { width, height }, locale, reducedMotion: 'reduce' })
  await context.addInitScript(([locale]) => {
    try {
      localStorage.setItem('app_theme', 'light')
      localStorage.setItem('app_locale', locale)
      localStorage.setItem('app_density', 'compact')
      localStorage.setItem('list_keys_hint', '1')
    } catch {
      // 存不进就按站点默认
    }
    window.__layoutShift = 0
    new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) if (!entry.hadRecentInput) window.__layoutShift += entry.value
    }).observe({ type: 'layout-shift', buffered: true })
  }, [locale])
  await context.route('**/api/**', (route) => {
    const request = route.request()
    if (request.method() !== 'GET' || new URL(request.url()).pathname.endsWith('/live-events')) return route.abort()
    return route.fallback()
  })
  const page = await context.newPage()
  const errors = []
  page.on('pageerror', (error) => errors.push(String(error.message).slice(0, 160)))
  const result = { page: spec.name, size: `${width}×${height}`, locale, failures: [], notes: [] }
  try {
    await page.goto(base + spec.path, { waitUntil: 'domcontentloaded', timeout: 60_000 })
    await page.waitForSelector(spec.ready, { timeout: 45_000 })
    await page.waitForTimeout(SETTLE_MS)
    const shot = {
      cls: await page.evaluate(() => window.__layoutShift),
      overflow: await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth),
      whole: spec.whole ? await page.evaluate(countWhole, spec.whole[0]) : null,
      fits: spec.fits ? await page.evaluate(fitsInView, spec.fits[0]) : null,
    }
    result.notes.push(`CLS ${shot.cls.toFixed(3)}`)
    if (shot.cls > CLS_LIMIT) result.failures.push(`CLS ${shot.cls.toFixed(3)} > ${CLS_LIMIT}`)
    if (shot.overflow > 0) result.failures.push(`横向溢出 ${shot.overflow}px`)
    if (spec.whole) {
      const floor = spec.whole[1][width][locale === 'zh-CN' ? 0 : 1]
      result.notes.push(`首屏 ${shot.whole} 条（≥${floor}）`)
      if (shot.whole < floor) result.failures.push(`首屏完整条目 ${shot.whole} < ${floor}`)
    }
    if (spec.fits && width >= spec.fits[1]) {
      result.notes.push(shot.fits ? '整块在首屏' : '整块不在首屏')
      if (!shot.fits) result.failures.push(`${spec.fits[0]} 没有整个落在首屏里`)
    }
    if (spec.keys) {
      const problems = await checkKeys(page)
      result.notes.push(problems.length ? '键盘流有问题' : '键盘流正常')
      result.failures.push(...problems)
    }
  } catch (error) {
    result.failures.push(`没跑完：${String(error.message).split('\n')[0]}`)
    result.unfinished = true
  }
  if (errors.length) result.failures.push(`页面报错：${errors.join(' | ')}`)
  if (result.failures.length && reportDir) {
    await page.screenshot({ path: `${reportDir}/${spec.name}-${width}-${locale}.png` }).catch(() => {})
  }
  await context.close()
  return result
}

const jobs = PAGES.filter((spec) => !only || only.has(spec.name))
  .flatMap((spec) => SIZES.flatMap((size) => LOCALES.map((locale) => [spec, size, locale])))
const results = []
const workers = Array.from({ length: Math.max(1, Number(env.LAYOUT_CONCURRENCY) || 3) }, async () => {
  while (jobs.length) {
    const job = jobs.shift()
    const first = await measure(...job)
    // 网络抖一下导致没加载完的，再跑一次。
    results.push(first.unfinished ? await measure(...job) : first)
  }
})
try {
  await Promise.all(workers)
} finally {
  await browser.close()
}

const order = (result) => [PAGES.findIndex((spec) => spec.name === result.page), SIZES.findIndex(([width]) => result.size.startsWith(`${width}×`)), LOCALES.indexOf(result.locale)]
results.sort((a, b) => order(a).reduce((sign, value, index) => sign || value - order(b)[index], 0))
for (const result of results) {
  console.log(`${result.failures.length ? '✗' : '✓'} ${result.page.padEnd(13)} ${result.size.padEnd(9)} ${result.locale}  ${result.notes.join('，')}`)
  for (const failure of result.failures) console.log(`    ${failure}`)
}
const failed = results.filter((result) => result.failures.length)
console.log(`\n${base}：${results.length} 个组合，${failed.length} 个超预算。`)
process.exitCode = failed.length ? 1 : 0
