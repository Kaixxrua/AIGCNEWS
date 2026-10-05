import {
  getCurrentInstance,
  onActivated,
  onBeforeUnmount,
  onDeactivated,
  onMounted,
  shallowRef,
  watchEffect,
} from 'vue'
import { useRoute, type RouteLocationNormalizedLoaded, type RouteRecordNameGeneric, type Router } from 'vue-router'
import i18n from '@/i18n'
import { installSeoMessages } from '@/i18n/locales/seo'

/**
 * 每页的 <title>、meta description、canonical 与 noindex。
 *
 * 各路径拿到的都是同一份 index.html，静态 head 只有首页那一份；Google 渲染 JS 后读的是这里写进
 * document 的值，所以按路由名给每页单独的标题和描述，详情页再用 usePageHead 换成论文标题、素材名。
 * 内容不存在（论文 404、素材 id 不在目录里）时标 noindex、不给 canonical，免得被当成正常页面收录。
 * canonical 一律指主站：备用入口 aigcradar.online 是整站镜像，不该和主站抢收录。筛选、来源标记之类的查询参数
 * 不进 canonical；决定页面内容的参数（某一期简报的 ?date=）由页面经 canonicalQuery 交代。
 */

export const SITE_ORIGIN = 'https://aigcnews.cn'
const BRAND = 'AIGCNEWS'
const DESCRIPTION_LIMIT = 160

/** 路由名 → seo.titles.* 的键；表里没有的页面用默认标题。 */
const ROUTE_TITLE_KEYS: Readonly<Record<string, string>> = {
  dashboard: 'home',
  'github-projects': 'projects',
  'recommended-websites': 'websites',
  'ui-library': 'uiLibrary',
  report: 'report',
  subscriptions: 'subscriptions',
  'x-board': 'xboard',
  'mcp-connect': 'mcp',
  dsh: 'dsh',
  monitor: 'monitor',
  'paper-read': 'paper',
  disclaimer: 'disclaimer',
  privacy: 'privacy',
  membership: 'membership',
  'membership-checkout': 'checkout',
  contact: 'contact',
  register: 'register',
  'oauth-callback': 'oauth',
  'oauth-action-callback': 'oauth',
}

/** 有专门描述的页面（seo.descriptions.*），其余用 default。 */
const DESCRIBED_PAGES = new Set(['projects', 'websites', 'uiLibrary', 'report', 'xboard', 'mcp', 'dsh', 'membership', 'disclaimer', 'privacy'])

export interface PageHeadOverride {
  /** 页面自己的标题（论文标题、素材名），会拼上品牌后缀。 */
  title?: string | null
  description?: string | null
  /** 内容不存在：不让搜索引擎收录。 */
  noindex?: boolean
  /** 决定页面内容、canonical 里要保留的查询参数；空值不写。 */
  canonicalQuery?: Readonly<Record<string, string | null | undefined>>
}

export interface PageHead {
  title: string
  description: string
  /** noindex 的页面没有 canonical。 */
  canonical: string | null
  noindex: boolean
}

type Translate = (key: string) => string

function pageKey(route: RouteLocationNormalizedLoaded): string | null {
  const key = ROUTE_TITLE_KEYS[String(route.name ?? '')] ?? null
  // 「我的网页收藏」与项目库共用 /projects，只差 source=website。
  if (key === 'projects' && route.query.source === 'website') return 'websiteCollection'
  return key
}

function compact(text: string | null | undefined): string {
  return (text ?? '').replace(/\s+/g, ' ').trim()
}

function clip(text: string, limit: number): string {
  const chars = [...text]
  return chars.length > limit ? `${chars.slice(0, limit - 1).join('').trimEnd()}…` : text
}

export function canonicalUrl(route: RouteLocationNormalizedLoaded, keep?: PageHeadOverride['canonicalQuery']): string {
  const path = route.path.length > 1 ? route.path.replace(/\/+$/, '') : '/'
  const params = new URLSearchParams()
  if (pageKey(route) === 'websiteCollection') params.set('source', 'website')
  for (const [name, value] of Object.entries(keep ?? {})) if (value) params.set(name, value)
  const query = params.toString()
  return `${SITE_ORIGIN}${path}${query ? `?${query}` : ''}`
}

export function resolvePageHead(
  route: RouteLocationNormalizedLoaded,
  override: PageHeadOverride | null,
  t: Translate,
): PageHead {
  const key = pageKey(route)
  const ownTitle = compact(override?.title)
  const title = ownTitle
    ? `${ownTitle} · ${BRAND}`
    : key && key !== 'home' ? `${t(`seo.titles.${key}`)} · ${BRAND}` : t('seo.titles.home')
  const ownDescription = compact(override?.description)
  const description = ownDescription
    ? clip(ownDescription, DESCRIPTION_LIMIT)
    : t(`seo.descriptions.${key && DESCRIBED_PAGES.has(key) ? key : 'default'}`)
  const noindex = override?.noindex === true
  return { title, description, canonical: noindex ? null : canonicalUrl(route, override?.canonicalQuery), noindex }
}

function upsertMeta(doc: Document, attribute: 'name' | 'property', key: string, content: string | null): void {
  let element = doc.head.querySelector<HTMLMetaElement>(`meta[${attribute}="${key}"]`)
  if (content === null) {
    element?.remove()
    return
  }
  if (!element) {
    element = doc.createElement('meta')
    element.setAttribute(attribute, key)
    doc.head.appendChild(element)
  }
  if (element.content !== content) element.content = content
}

function upsertCanonical(doc: Document, href: string | null): void {
  let element = doc.head.querySelector<HTMLLinkElement>('link[rel="canonical"]')
  if (href === null) {
    element?.remove()
    return
  }
  if (!element) {
    element = doc.createElement('link')
    element.rel = 'canonical'
    doc.head.appendChild(element)
  }
  if (element.getAttribute('href') !== href) element.setAttribute('href', href)
}

export function applyPageHead(doc: Document, head: PageHead): void {
  if (doc.title !== head.title) doc.title = head.title
  upsertMeta(doc, 'name', 'description', head.description)
  upsertMeta(doc, 'property', 'og:title', head.title)
  upsertMeta(doc, 'property', 'og:description', head.description)
  upsertMeta(doc, 'property', 'og:url', head.canonical ?? `${SITE_ORIGIN}/`)
  upsertMeta(doc, 'name', 'robots', head.noindex ? 'noindex' : null)
  upsertCanonical(doc, head.canonical)
}

// ── 视图覆盖 ─────────────────────────────────────────────────────────────────
// 页面切换时新旧两页会同时挂着（离场动画、KeepAlive），所以覆盖按登记先后排，且只认当前路由名下的；
// 每个视图只撤自己登记的那一条。

interface OverrideEntry {
  id: number
  routeName: RouteRecordNameGeneric | undefined
  read: () => PageHeadOverride | null
}

const entries = shallowRef<readonly OverrideEntry[]>([])
let nextEntryId = 0

function activeOverride(route: RouteLocationNormalizedLoaded): PageHeadOverride | null {
  for (let index = entries.value.length - 1; index >= 0; index -= 1) {
    const entry = entries.value[index]!
    if (entry.routeName !== route.name) continue
    const override = entry.read()
    if (override) return override
  }
  return null
}

/**
 * 详情页登记自己的标题/描述/noindex，只在建这个视图时的路由下生效。read 在 watchEffect 里求值，
 * 读到的响应式数据变了 head 随之更新；返回 null 表示沿用路由级的默认值。
 */
export function usePageHead(read: () => PageHeadOverride | null): void {
  if (!getCurrentInstance()) return
  const entry: OverrideEntry = { id: nextEntryId++, routeName: useRoute()?.name, read }
  const remove = () => { entries.value = entries.value.filter((item) => item.id !== entry.id) }
  const add = () => { entries.value = [...entries.value.filter((item) => item.id !== entry.id), entry] }
  onMounted(add)
  onActivated(add)
  onDeactivated(remove)
  onBeforeUnmount(remove)
}

/** 跟着当前路由、语言和视图覆盖改写 head；返回停止函数（应用里一直挂着，测试里用来收尾）。 */
export function installPageHead(router: Router, doc: Document = document): () => void {
  installSeoMessages()
  const t: Translate = (key) => i18n.global.t(key)
  return watchEffect(() => {
    // 先读 locale：切换语言时整块重算。
    void i18n.global.locale.value
    const route = router.currentRoute.value
    applyPageHead(doc, resolvePageHead(route, activeOverride(route), t))
  })
}

export function __resetPageHeadForTest(): void {
  entries.value = []
}
