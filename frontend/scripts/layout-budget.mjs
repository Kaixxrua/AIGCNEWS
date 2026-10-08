// 版面预算：桌面四档、手机三档视口 × 中英文，逐页查落地页、布局偏移（CLS）、横向溢出、首屏条目数。桌面列表页
// 再按一遍 j / k / ? / Esc；弹窗要整个落在屏内、出现后不自己挪位置，里面的控件都点得到。超预算的组合逐条列出，非零退出。
// 说明见 docs/layout-budget.md。
//
//   VITE_API_PROXY_TARGET=https://aigcnews.cn npx vite preview --port 4173   # 先 vite build，另开终端
//   npm run check:layout                                                       # 默认测 http://127.0.0.1:4173
//
// 只读：/api 下除 GET 以外的请求一律在浏览器里拦下、回一个空的成功响应，实时事件流也不连，所以可以直接对着生产跑。
// LAYOUT_BASE_URL     被测站点，默认 http://127.0.0.1:4173
// LAYOUT_RESOLVE      把域名钉到一个边缘，如 aigcnews.cn=<边缘 IP>；钉了就不走代理
// LAYOUT_PROFILE      只测一套：desktop 或 mobile，缺省两套都测
// LAYOUT_PAGES        只测这几项，逗号分隔，如 report,projects
// LAYOUT_CONCURRENCY  同时开几页，默认 3
// LAYOUT_REPORT_DIR   超预算的组合截一张首屏存到这里
// CHROME_PATH         换用指定的 Chromium，缺省用 Playwright 自带的
import { chromium } from 'playwright'
import { mkdir } from 'node:fs/promises'

const LOCALES = ['zh-CN', 'en-US']
const CLS_LIMIT = 0.1
const SETTLE_MS = 3000
const DIALOG_SETTLE_MS = 1000

// dialog：[打开的标志, 要整个落在屏内的那层]，只写一个就是同一个元素。登录弹窗的卡片出现算打开，外面那层负责滚动。
const LOGIN_DIALOG = ['.comic-auth .auth-card', '.comic-auth > div']
const MORE_BUTTON = '.mobile-nav button[aria-haspopup="dialog"]'
// lands：就绪后地址该在的路径，缺省取 path 的；可以给几个。站长推荐有内容时，游客打开网页收藏会被转到站长推荐
// （守卫最多等 2.5 秒），两处都算落对。
const WEBSITES = { name: 'websites', path: '/projects?source=website', lands: ['/projects', '/websites'], ready: 'h1' }
// 游客打开要登录的页面（订阅、会员结账），会被送回首页并弹出登录框。
const GATE = { name: 'gate', path: '/subscriptions', lands: '/', ready: LOGIN_DIALOG[0], dialog: LOGIN_DIALOG }

const PROFILES = [
  {
    name: 'desktop',
    label: '桌面',
    sizes: [[1024, 640], [1350, 657], [1536, 730], [1920, 960]],
    // whole：首屏里上下沿都露出来、没被报头页脚盖住的条目，按宽度给 [中文, 英文] 两个下限。数据天天变的页
    // 留了余量，简报钉在一期上。fits：这块要整个落在首屏里（会员对比表、MCP 的接入命令）。keys：走一遍列表键盘流。
    // 订阅页要登录，游客会被送回首页，量不到页面本身，量的是游客看到的首页加登录框（gate）；
    // 自己点开的登录弹窗从 dock 上的账号按钮打开来测（login）。
    pages: [
      { name: 'home', path: '/', ready: '.ui-inspiration', fits: ['.ui-inspiration', 1024], fitChildren: '.dashboard-sidebar' },
      { name: 'report', path: '/report?date=2026-10-03', ready: '.report-broadsheet__item', whole: ['.report-broadsheet__item', { 1024: [0, 0], 1350: [2, 0], 1536: [2, 2], 1920: [7, 5] }], keys: true },
      { name: 'projects', path: '/projects', ready: '.project-row', whole: ['.project-row', { 1024: [2, 2], 1350: [4, 2], 1536: [5, 4], 1920: [8, 8] }], keys: true },
      { name: 'x', path: '/x', ready: '.tweet-card', whole: ['.tweet-card', { 1024: [2, 2], 1350: [3, 3], 1536: [4, 4], 1920: [6, 6] }], keys: true },
      { name: 'ui-library', path: '/ui-library', ready: '.ui-library__card', whole: ['.ui-library__card', { 1024: [3, 3], 1350: [10, 10], 1536: [12, 12], 1920: [21, 21] }] },
      { name: 'membership', path: '/membership', ready: '.membership-card--compare', fits: ['.membership-card--compare', 1350] },
      { name: 'mcp', path: '/mcp', ready: '.command-preview', fits: ['.command-preview', 1024] },
      WEBSITES,
      { name: 'dsh', path: '/dsh', ready: 'h1' },
      { name: 'not-found', path: '/no-such-page', ready: 'h1' },
      { name: 'login', path: '/privacy', ready: 'h1', taps: ['.dock-item--account'], dialog: LOGIN_DIALOG },
      GATE,
    ],
  },
  {
    name: 'mobile',
    label: '手机',
    sizes: [[360, 740], [390, 664], [430, 740]],
    device: { isMobile: true, hasTouch: true, deviceScaleFactor: 3 },
    // 手机一屏装不下几张整卡，seen 数的是首屏里露出头的条目：顶边往下 24px 都在屏内，也没被报头、底栏挡住。
    // 下限同样分 [中文, 英文]；390×664 偏矮，首页和 UI 灵感库露不出头，记 0。
    // 订阅、会员结账要登录，游客看到的是首页加登录框（gate）；监控只对管理员开放，不测。
    // /login 不是路由，自己点开的登录弹窗从「更多」菜单打开来测（login）。
    // 第三方登录的两个回调页一打开就要兑换一次性凭据（POST），脚本只读，也不测。
    pages: [
      { name: 'home', path: '/', ready: '.ranking-row', seen: ['.ranking-row', { 360: [1, 1], 390: [0, 0], 430: [1, 1] }] },
      { name: 'projects', path: '/projects', ready: '.project-card', seen: ['.project-card', { 360: [1, 1], 390: [1, 1], 430: [1, 1] }] },
      WEBSITES,
      { name: 'ui-library', path: '/ui-library', ready: '.ui-library__card', seen: ['.ui-library__card', { 360: [1, 1], 390: [0, 0], 430: [1, 1] }] },
      { name: 'ui-item', path: '/ui-library/ruixen-claude-chat-input', ready: 'dialog.ui-detail[open]', dialog: ['dialog.ui-detail[open]'] },
      { name: 'report', path: '/report?date=2026-10-03', ready: '.report-section', seen: ['.report-section', { 360: [1, 1], 390: [1, 1], 430: [1, 1] }] },
      { name: 'x', path: '/x', ready: '.tweet-card', seen: ['.tweet-card', { 360: [1, 1], 390: [1, 1], 430: [1, 1] }] },
      { name: 'mcp', path: '/mcp', ready: 'h1' },
      { name: 'dsh', path: '/dsh', ready: 'h1' },
      { name: 'membership', path: '/membership', ready: 'h1' },
      { name: 'contact', path: '/contact', ready: 'h1' },
      { name: 'paper', path: '/papers/bf97c1cb0bd009600eb3af2e676883cc/read', ready: 'h1' },
      { name: 'disclaimer', path: '/disclaimer', ready: 'h1' },
      { name: 'privacy', path: '/privacy', ready: 'h1' },
      { name: 'register', path: '/register', ready: 'h1' },
      { name: 'recommended', path: '/websites', ready: 'h1' },
      { name: 'not-found', path: '/no-such-page', ready: 'h1' },
      { name: 'forgot', path: '/forgot-password', lands: '/', ready: LOGIN_DIALOG[0], dialog: LOGIN_DIALOG },
      { name: 'more', path: '/privacy', ready: 'h1', taps: [MORE_BUTTON], dialog: ['dialog.mobile-menu[open]'] },
      { name: 'login', path: '/privacy', ready: 'h1', taps: [MORE_BUTTON, '.mobile-menu__account button'], dialog: LOGIN_DIALOG },
      GATE,
    ],
  },
]

const env = process.env
const base = (env.LAYOUT_BASE_URL || 'http://127.0.0.1:4173').replace(/\/$/, '')
const only = env.LAYOUT_PAGES ? new Set(env.LAYOUT_PAGES.split(',').map((name) => name.trim())) : null
const profiles = PROFILES.filter((profile) => !env.LAYOUT_PROFILE || profile.name === env.LAYOUT_PROFILE)
if (!profiles.length) throw new Error(`LAYOUT_PROFILE 只能是 ${PROFILES.map((profile) => profile.name).join(' 或 ')}`)
const reportDir = env.LAYOUT_REPORT_DIR
if (reportDir) await mkdir(reportDir, { recursive: true })

const args = []
if (env.LAYOUT_RESOLVE) {
  const [host, ip] = env.LAYOUT_RESOLVE.split('=')
  args.push(`--host-resolver-rules=MAP ${host} ${ip}`, '--no-proxy-server')
}
const browser = await chromium.launch({ headless: true, executablePath: env.CHROME_PATH || undefined, args })
// UA 里留着 HeadlessChrome，站点按自动化流量计，不算进访客数。
const MOBILE_UA = `Mozilla/5.0 (Linux; Android 14; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) HeadlessChrome/${browser.version()} Mobile Safari/537.36`

// 首屏完整条目：整块在视口里，上下沿各取一点做命中测试，被报头、页脚、浮层或滚动容器裁掉的不算。
// 连同页面上一共有几条一起报：数据少的日子（推文墙按账号折叠后只剩几张卡）凑不满下限，不算版面问题。
function countWhole(selector) {
  let count = 0
  const items = document.querySelectorAll(selector)
  for (const el of items) {
    const box = el.getBoundingClientRect()
    if (!box.width || !box.height || box.top < 0 || box.left < 0 || box.bottom > innerHeight || box.right > innerWidth) continue
    const x = box.left + box.width / 2
    const sees = (y) => {
      const hit = document.elementFromPoint(x, y)
      return !!hit && el.contains(hit)
    }
    if (sees(box.top + 2) && sees(box.bottom - 2)) count++
  }
  return { count, total: items.length }
}

// 首屏露头的条目：顶边在屏内，往下 24px 也在屏内；顶边下 2px、22px 两处命中测试都打在条目上。
function countSeen(selector) {
  let count = 0
  const items = document.querySelectorAll(selector)
  for (const el of items) {
    const box = el.getBoundingClientRect()
    if (!box.width || !box.height || box.top < 0 || box.top + 24 > innerHeight || box.right <= 0 || box.left >= innerWidth) continue
    const x = (Math.max(box.left, 0) + Math.min(box.right, innerWidth)) / 2
    const sees = (y) => {
      const hit = document.elementFromPoint(x, y)
      return !!hit && el.contains(hit)
    }
    if (sees(box.top + 2) && sees(box.top + 22)) count++
  }
  return { count, total: items.length }
}

function fitsInView(selector) {
  const box = document.querySelector(selector)?.getBoundingClientRect()
  return !!box && box.top >= 0 && box.bottom <= innerHeight
}

// 横向溢出：文档比视口宽，或手机浏览器为了装下过宽的内容把视口撑宽了。超了就找出最外层的越界元素，最多报三个。
// 固定定位的背景层、底栏、弹窗只是跟着撑宽的视口变宽，不是起因；被祖先的 overflow 裁住的、看不见的也不算。
function horizontalOverflow(width) {
  const root = document.documentElement
  const px = Math.max(root.scrollWidth - root.clientWidth, innerWidth - width)
  const offenders = []
  if (px <= 0) return { px, offenders }
  const outside = (box) => box.right > width + 1 || box.left < -1
  const excused = (el) => {
    for (let node = el; node && node !== document.body; node = node.parentElement) {
      const style = getComputedStyle(node)
      if (style.position === 'fixed') return true
      if (node !== el && /(hidden|clip|auto|scroll)/.test(style.overflowX) && !outside(node.getBoundingClientRect())) return true
    }
    return false
  }
  for (const el of document.body.querySelectorAll('*')) {
    const box = el.getBoundingClientRect()
    if (!box.width || !box.height || !outside(box) || getComputedStyle(el).visibility === 'hidden' || excused(el)) continue
    const parent = el.parentElement
    if (parent && parent !== document.body && outside(parent.getBoundingClientRect()) && !excused(parent)) continue
    const classes = typeof el.className === 'string' ? el.className.trim().split(/\s+/).filter(Boolean).slice(0, 2) : []
    offenders.push(`${el.tagName.toLowerCase()}${classes.map((name) => `.${name}`).join('')}（${Math.round(box.left)}→${Math.round(box.right)}）`)
    if (offenders.length === 3) break
  }
  return { px, offenders }
}

// 内容越出屏幕边，被整页级的容器裁掉。站点外壳和 body 都裁横向，多数溢出不会让页面横滑，而是表现成这样。
// 整页级指横跨视口的裁切层，或高过半屏的滚动层；窄于视口的横滑条、走马灯是组件自己裁自己，不算。
// 只看有字或能点的元素，报最外层的，最多三个；整个停在屏外的（抽屉、跳转链接）不算。
function cutOff(width) {
  const pageLevel = (node, style) => {
    const clip = node.getBoundingClientRect()
    return clip.left <= 0.5 && clip.right >= width - 0.5 && (/(hidden|clip)/.test(style.overflowX) || clip.height >= innerHeight / 2)
  }
  const contained = (el) => {
    for (let node = el.parentElement; node && node !== document.documentElement; node = node.parentElement) {
      const style = getComputedStyle(node)
      if (style.overflowX !== 'visible' && !pageLevel(node, style)) return true
    }
    return false
  }
  const found = []
  const cut = []
  for (const el of document.body.querySelectorAll('*')) {
    const ownText = [...el.childNodes].some((node) => node.nodeType === Node.TEXT_NODE && node.textContent.trim())
    if (!ownText && !el.matches('a[href], button, input, select, textarea, img, svg')) continue
    const box = el.getBoundingClientRect()
    if (!box.width || !box.height || (box.left >= -1 && box.right <= width + 1) || box.right <= 0 || box.left >= width) continue
    const style = getComputedStyle(el)
    if (style.visibility === 'hidden' || style.opacity === '0' || found.some((outer) => outer.contains(el)) || contained(el)) continue
    found.push(el)
    const classes = typeof el.className === 'string' ? el.className.trim().split(/\s+/).filter(Boolean).slice(0, 2) : []
    const text = (el.getAttribute('aria-label') || el.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 16)
    cut.push(`${el.tagName.toLowerCase()}${classes.map((name) => `.${name}`).join('')}${text ? `「${text}」` : ''}（${Math.round(box.left)}→${Math.round(box.right)}）`)
    if (cut.length === 3) break
  }
  return cut
}

// 弹窗出现后又挪了位置：逐帧记下的挪动，上沿或下沿累计超过 4px 就算。内容晚到把居中的卡片撑高时，卡片会整张
// 跳位，layout-shift 不一定记得到（实测登录框跳 56px，有的轮次一条都没报）。
function panelMoved() {
  const moves = window.__panelMoves ?? []
  const total = (edge) => moves.reduce((sum, [from, to]) => sum + Math.abs(to[edge] - from[edge]), 0)
  if (Math.max(total(0), total(1)) <= 4) return null
  const shown = moves.slice(0, 3).map(([from, to]) => `上沿 ${from[0]}→${to[0]}，下沿 ${from[1]}→${to[1]}`).join('；')
  return moves.length > 3 ? `${shown} 等 ${moves.length} 次` : shown
}

// 弹窗：外层整个落在屏内；里面每个看得见的控件滚到中间后，可见部分的正中命中的是它自己或它的 label。
function checkDialog([open, panelSelector = open]) {
  const describe = (el) => {
    const classes = typeof el.className === 'string' ? el.className.trim().split(/\s+/).filter(Boolean).slice(0, 2) : []
    const text = (el.getAttribute('aria-label') || el.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 16)
    return `${el.tagName.toLowerCase()}${classes.map((name) => `.${name}`).join('')}${text ? `「${text}」` : ''}`
  }
  const panel = document.querySelector(panelSelector)
  if (!panel) return null
  const box = panel.getBoundingClientRect()
  const inside = box.top >= -1 && box.left >= -1 && box.bottom <= innerHeight + 1 && box.right <= innerWidth + 1
  const blocked = []
  let controls = 0
  for (const control of panel.querySelectorAll('a[href], button, input, select, textarea, [tabindex]:not([tabindex="-1"])')) {
    const own = control.getBoundingClientRect()
    if (own.width < 4 || own.height < 4 || getComputedStyle(control).visibility === 'hidden') continue
    controls++
    control.scrollIntoView({ block: 'center', inline: 'center', behavior: 'instant' })
    const at = control.getBoundingClientRect()
    const left = Math.max(at.left, 0)
    const right = Math.min(at.right, innerWidth)
    const top = Math.max(at.top, 0)
    const bottom = Math.min(at.bottom, innerHeight)
    if (right <= left || bottom <= top) {
      blocked.push(`${describe(control)}滚不进屏内`)
      continue
    }
    const hit = document.elementFromPoint((left + right) / 2, (top + bottom) / 2)
    if (hit && (control.contains(hit) || [...(control.labels ?? [])].some((label) => label.contains(hit)))) continue
    blocked.push(`${describe(control)}被${hit ? describe(hit) : '空白'}挡住`)
  }
  return { inside, box: [box.left, box.top, box.right, box.bottom].map(Math.round), controls, blocked }
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

async function measure(profile, spec, [width, height], locale) {
  const context = await browser.newContext({
    viewport: { width, height },
    locale,
    reducedMotion: 'reduce',
    ...profile.device,
    ...(profile.device ? { userAgent: MOBILE_UA } : {}),
  })
  await context.addInitScript(([locale, panel]) => {
    try {
      localStorage.setItem('app_theme', 'light')
      localStorage.setItem('app_locale', locale)
      localStorage.setItem('app_density', 'compact')
      localStorage.setItem('list_keys_hint', '1')
      // Measure normal page layouts; the onboarding overlay has its own flow checks.
      localStorage.setItem('aigcnews:onboarding:v1', JSON.stringify({ browserDone: true, users: {} }))
    } catch {
      // 存不进就按站点默认
    }
    window.__layoutShift = 0
    new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) if (!entry.hadRecentInput) window.__layoutShift += entry.value
    }).observe({ type: 'layout-shift', buffered: true })
    // 弹窗外层出现后逐帧看上下沿，挪了就记一笔给 panelMoved。只有网页字体刚加载完、弹窗里又没增删内容的那一帧不记：
    // 换上字体后文字重排，卡片跟着挪几像素是字体闪动，算在 CLS 里。
    if (!panel) return
    window.__panelMoves = []
    const loadedFonts = () => [...document.fonts].filter((face) => face.status === 'loaded').length
    let edited = false
    new MutationObserver((records) => {
      const box = document.querySelector(panel)
      if (box && records.some((record) => box.contains(record.target))) edited = true
    }).observe(document, { childList: true, characterData: true, subtree: true })
    let last = null
    let fonts = 0
    const watch = () => {
      const box = document.querySelector(panel)?.getBoundingClientRect()
      const edges = box?.height ? [box.top, box.bottom].map(Math.round) : null
      const loaded = loadedFonts()
      const fontSwap = loaded !== fonts && !edited
      if (edges && last && !fontSwap && (edges[0] !== last[0] || edges[1] !== last[1])) window.__panelMoves.push([last, edges])
      last = edges
      fonts = loaded
      edited = false
      requestAnimationFrame(watch)
    }
    requestAnimationFrame(watch)
  }, [locale, spec.dialog ? spec.dialog[1] ?? spec.dialog[0] : null])
  // 写请求（游客只有访问计数这一个）就地回空的成功响应：直接掐断，站点会当成连不上主站，再碰上一次网络抖动
  // 就弹出「换备用入口」的提示，压在弹窗上。
  await context.route('**/api/**', (route) => {
    const request = route.request()
    if (request.method() !== 'GET') return route.fulfill({ status: 204 })
    if (new URL(request.url()).pathname.endsWith('/live-events')) return route.abort()
    return route.fallback()
  })
  const page = await context.newPage()
  const errors = []
  page.on('pageerror', (error) => errors.push(String(error.message).slice(0, 160)))
  const result = { profile: profile.name, page: spec.name, size: `${width}×${height}`, locale, failures: [], notes: [] }
  try {
    await page.goto(base + spec.path, { waitUntil: 'domcontentloaded', timeout: 60_000 })
    await page.waitForSelector(spec.ready, { timeout: 45_000 })
    // 要登录的页面会把游客送回首页，首页的代码没下完时地址还停在原处；等它换过去再量，一直没换过去就算落错。
    const expected = [spec.lands ?? new URL(spec.path, base).pathname].flat()
    await page.waitForFunction((paths) => paths.includes(location.pathname), expected, { timeout: 15_000 }).catch(() => {})
    await page.waitForTimeout(SETTLE_MS)
    const landed = await page.evaluate(() => location.pathname)
    if (!expected.includes(landed)) result.failures.push(`落在 ${landed}，不在 ${expected.join(' 或 ')}`)
    for (const selector of spec.taps ?? []) {
      const target = page.locator(selector).first()
      await (profile.device ? target.tap({ timeout: 10_000 }) : target.click({ timeout: 10_000 }))
      await page.waitForTimeout(300)
    }
    if (spec.dialog) {
      await page.waitForSelector(spec.dialog[0], { timeout: 10_000 })
      await page.waitForTimeout(DIALOG_SETTLE_MS)
    }
    const counted = spec.whole ?? spec.seen
    const overflow = await page.evaluate(horizontalOverflow, width)
    const shot = {
      cls: await page.evaluate(() => window.__layoutShift),
      overflow,
      // 视口被撑宽时，跟着变宽的底栏、弹窗也会越界，先只报溢出。
      cut: overflow.px > 0 ? [] : await page.evaluate(cutOff, width),
      first: counted ? await page.evaluate(spec.whole ? countWhole : countSeen, counted[0]) : null,
      fits: spec.fits ? await page.evaluate(fitsInView, spec.fits[0]) : null,
    }
    result.notes.push(`CLS ${shot.cls.toFixed(3)}`)
    if (shot.cls > CLS_LIMIT) result.failures.push(`CLS ${shot.cls.toFixed(3)} > ${CLS_LIMIT}`)
    if (shot.overflow.px > 0) result.failures.push(`横向溢出 ${shot.overflow.px}px${shot.overflow.offenders.length ? `：${shot.overflow.offenders.join('；')}` : ''}`)
    if (shot.cut.length) result.failures.push(`内容出了屏幕边：${shot.cut.join('；')}`)
    if (counted) {
      // 页面上的条目本来就不到下限时，要求它们全都落在首屏；一条都没有算失败，多半是数据没取到。
      const { count, total } = shot.first
      const floor = Math.min(counted[1][width][locale === 'zh-CN' ? 0 : 1], total)
      const what = spec.whole ? '首屏' : '首屏露头'
      result.notes.push(`${what} ${count} 条（≥${floor}${floor < total ? '' : `，页面共 ${total} 条`}）`)
      if (!total) result.failures.push('页面上没有条目')
      else if (count < floor) result.failures.push(`${what}条目 ${count} < ${floor}`)
    }
    if (spec.fits && width >= spec.fits[1]) {
      result.notes.push(shot.fits ? '整块在首屏' : '整块不在首屏')
      if (!shot.fits) result.failures.push(`${spec.fits[0]} 没有整个落在首屏里`)
    }
    if (spec.fitChildren) {
      const children = await page.evaluate(countWhole, `${spec.fitChildren} > *`)
      const scroll = await page.locator(spec.fitChildren).evaluate((element) => ({
        overflow: element.scrollHeight - element.clientHeight,
        top: element.scrollTop,
      }))
      if (!children.total || children.count !== children.total || scroll.overflow > 1 || scroll.top !== 0) {
        result.failures.push(`${spec.fitChildren} 首屏仅完整显示 ${children.count}/${children.total} 张卡片，溢出 ${scroll.overflow}px、已滚动 ${scroll.top}px`)
      } else result.notes.push('侧栏全部卡片无需滚动即可完整显示')
    }
    if (spec.keys) {
      const problems = await checkKeys(page)
      result.notes.push(problems.length ? '键盘流有问题' : '键盘流正常')
      result.failures.push(...problems)
    }
    if (spec.dialog) {
      const moved = await page.evaluate(panelMoved)
      if (moved) result.failures.push(`弹窗出现后又挪了位置：${moved}`)
      // 最后查：要把控件逐个滚到中间，会改动滚动位置。
      const dialog = await page.evaluate(checkDialog, spec.dialog)
      if (!dialog) result.failures.push(`找不到 ${spec.dialog[1] ?? spec.dialog[0]}`)
      else {
        result.notes.push(`弹窗 ${dialog.controls} 个控件`)
        if (!dialog.inside) result.failures.push(`弹窗出了屏（${dialog.box.join(', ')}）`)
        if (!dialog.controls) result.failures.push('弹窗里没有可点的控件')
        if (dialog.blocked.length) result.failures.push(`点不到 ${dialog.blocked.length} 个控件：${dialog.blocked.slice(0, 3).join('；')}`)
      }
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

const jobs = profiles.flatMap((profile) => profile.pages.filter((spec) => !only || only.has(spec.name))
  .flatMap((spec) => profile.sizes.flatMap((size) => LOCALES.map((locale) => [profile, spec, size, locale]))))
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

const totals = []
for (const profile of profiles) {
  const own = results.filter((result) => result.profile === profile.name)
  if (!own.length) continue
  const order = (result) => [profile.pages.findIndex((spec) => spec.name === result.page), profile.sizes.findIndex(([width]) => result.size.startsWith(`${width}×`)), LOCALES.indexOf(result.locale)]
  own.sort((a, b) => order(a).reduce((sign, value, index) => sign || value - order(b)[index], 0))
  console.log(`\n${profile.label}`)
  for (const result of own) {
    console.log(`${result.failures.length ? '✗' : '✓'} ${result.page.padEnd(13)} ${result.size.padEnd(9)} ${result.locale}  ${result.notes.join('，')}`)
    for (const failure of result.failures) console.log(`    ${failure}`)
  }
  totals.push(`${profile.label} ${own.length} 个组合、${own.filter((result) => result.failures.length).length} 个超预算`)
}
const failed = results.filter((result) => result.failures.length)
console.log(`\n${base}：${totals.join('；')}。`)
process.exitCode = failed.length ? 1 : 0
