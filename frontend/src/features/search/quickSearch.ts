import type { RouteLocationRaw } from 'vue-router'
import type { AppLocale } from '@/i18n'
import { paperPlainText } from '@/features/papers/paperLatex'
import { formatProjectCount, projectDescription } from '@/features/projects/projectPresentation'
import { getReportTypeInfo, isReportKey } from '@/features/report/reportViewModel'
import { queryTerms, searchTemplates, type SearchableTemplate, type UiTemplate } from '@/features/ui-library/catalog'
import type { QuickSearchGroup, QuickSearchResult } from '@/services/search/searchApi'

/**
 * 站内速查（⌘K）的纯逻辑：查什么、结果怎么分组排成行、每行跳到哪、关键词怎么标出来。
 * 请求、焦点与动效在 QuickSearch.vue 里；哪个键打开面板在 quickSearchHotkey.ts。
 */
export type QuickSearchKind = 'recent' | 'projects' | 'papers' | 'briefings' | 'tweets' | 'templates'

export type QuickSearchTarget =
  | { type: 'route'; to: RouteLocationRaw }
  | { type: 'external'; href: string }
  /** 把这个词填回搜索框（最近搜过的词）。 */
  | { type: 'query'; q: string }

export interface QuickSearchRow {
  key: string
  kind: QuickSearchKind
  title: string
  /** 第二行：简介、摘要或截在命中处的一段正文，没有为空。 */
  detail: string
  /** 标题右侧的小字：星数、语言、作者、日期、简报种类。 */
  meta: string[]
  target: QuickSearchTarget
  /** 组末「查看全部」那一行。 */
  more: boolean
}

export interface QuickSearchSection {
  kind: QuickSearchKind
  total: number
  rows: QuickSearchRow[]
  /** 这一组没查成。 */
  failed: boolean
}

export type Translate = (key: string, named?: Record<string, unknown>) => string

export const QUICK_SEARCH_MAX_CHARS = 120
export const QUICK_SEARCH_DEBOUNCE_MS = 180
export const RECENT_QUERIES_KEY = 'quick_search_recent'
export const RECENT_QUERIES_MAX = 6

/**
 * 能拿去搜的词：全角转半角、空白并成一个空格，截到后端上限。至少两个字符，汉字一个就够（「图」「库」本身就是词）；不够时为空串。
 */
export function searchableQuery(raw: string): string {
  const q = raw.normalize('NFKC').replace(/\s+/g, ' ').trim().slice(0, QUICK_SEARCH_MAX_CHARS).trim()
  return q.length >= 2 || /\p{Script=Han}/u.test(q) ? q : ''
}

/** 站内速查只用得上目录里这几样字段，整份目录（含源码清单）读完就放掉。 */
export type QuickSearchTemplate = SearchableTemplate

export const slimTemplate = (item: UiTemplate): QuickSearchTemplate => ({
  id: item.id,
  name: item.name,
  description: item.description,
  provider: item.provider,
  aliases: item.aliases,
  frameworks: item.frameworks,
  category: item.category,
})

/** UI 素材按素材库同一套规则在本地查；一个有效词都没有（只剩停用词）时不算命中，免得列出整个目录。 */
export function matchTemplates(items: readonly QuickSearchTemplate[], q: string, limit: number): QuickSearchGroup<QuickSearchTemplate> {
  if (!q || !queryTerms(q, items).length) return { total: 0, items: [] }
  const matches = searchTemplates(items, q)
  return { total: matches.length, items: matches.slice(0, limit) }
}

export interface SectionInput {
  q: string
  result: QuickSearchResult | null
  templates: QuickSearchGroup<QuickSearchTemplate> | null
  /** 没查成的组（含整个请求失败时的四组、目录没读到时的 UI 素材）。 */
  failed: readonly QuickSearchKind[]
}

const route = (to: RouteLocationRaw): QuickSearchTarget => ({ type: 'route', to })
const row = (kind: QuickSearchKind, key: string, fields: Omit<QuickSearchRow, 'kind' | 'key' | 'more'>): QuickSearchRow => ({
  kind, key: `${kind}:${key}`, more: false, ...fields,
})
const moreRow = (kind: QuickSearchKind, title: string, to: RouteLocationRaw): QuickSearchRow => ({
  kind, key: `${kind}::more`, title, detail: '', meta: [], target: route(to), more: true,
})

/** 一行里只放得下第一作者：多人合著写成「某某 等 N 人」。 */
function paperAuthors(authors: string[], authorCount: number, t: Translate): string {
  const [name] = authors
  if (!name) return ''
  return Math.max(authorCount, authors.length) > 1 ? t('quickSearch.authors', { name, count: Math.max(authorCount, authors.length) }) : name
}

/** 按 项目、论文、简报、推文、UI 素材 的顺序排成分组；没命中的组不出现，没查成的组留一个带说明的组头。 */
export function buildSections({ q, result, templates, failed }: SectionInput, locale: AppLocale, t: Translate): QuickSearchSection[] {
  const sections: QuickSearchSection[] = []
  const push = (kind: QuickSearchKind, total: number, rows: QuickSearchRow[]) => {
    const isFailed = failed.includes(kind)
    if (rows.length || isFailed) sections.push({ kind, total: rows.length ? total : 0, rows, failed: isFailed })
  }
  const lang = locale === 'zh-CN' ? 'zh' : 'en'

  const projects = result?.projects
  if (projects || failed.includes('projects')) {
    const rows = (projects?.items ?? []).map(project => row('projects', project.fullName, {
      title: project.fullName,
      detail: projectDescription({ description: project.description, description_zh: project.descriptionZh, description_en: project.descriptionEn }, locale, ''),
      meta: [project.stars ? `★ ${formatProjectCount(project.stars, locale)}` : '', project.language].filter(Boolean),
      // 项目库里按全名筛出这一个，卡片上的趋势、分类与译文都在那里。
      target: route({ name: 'github-projects', query: { q: project.fullName } }),
    }))
    const total = projects?.total ?? 0
    if (rows.length && total > rows.length) rows.push(moreRow('projects', t('quickSearch.more.projects', { count: total }), { name: 'github-projects', query: { q } }))
    push('projects', total, rows)
  }

  const papers = result?.papers
  if (papers || failed.includes('papers')) {
    const rows = (papers?.items ?? []).map(paper => row('papers', paper.id, {
      // 标题、摘要里的 LaTeX 写法（\emph{…}、2\%、---）只留文字。
      title: paperPlainText(paper.title) || paper.id,
      detail: paperPlainText(paper.summary),
      meta: [paperAuthors(paper.authors, paper.authorCount, t), paper.date].filter(Boolean),
      target: route({ name: 'paper-read', params: { id: paper.id } }),
    }))
    push('papers', papers?.total ?? 0, rows)
  }

  const briefings = result?.briefings
  if (briefings || failed.includes('briefings')) {
    const rows: QuickSearchRow[] = []
    for (const briefing of briefings?.items ?? []) {
      if (!isReportKey(briefing.type)) continue
      const info = getReportTypeInfo(briefing.type)
      const name = info ? t(`report.type.${info.labelKey}`) : briefing.type
      rows.push(row('briefings', `${briefing.date}:${briefing.type}`, {
        title: briefing.lead || briefing.title || name,
        detail: briefing.snippet,
        meta: [t('saved.issue', { date: briefing.date, name })],
        target: route({ name: 'report', query: { date: briefing.date, type: briefing.type } }),
      }))
    }
    push('briefings', briefings?.total ?? 0, rows)
  }

  const tweets = result?.tweets
  if (tweets || failed.includes('tweets')) {
    const rows = (tweets?.items ?? []).filter(tweet => tweet.url).map(tweet => row('tweets', tweet.id || tweet.url, {
      title: tweet.author ? `@${tweet.author}` : t('quickSearch.tweet'),
      detail: tweet.text,
      meta: [tweet.date].filter(Boolean),
      target: { type: 'external', href: tweet.url },
    }))
    push('tweets', tweets?.total ?? 0, rows)
  }

  if (templates || failed.includes('templates')) {
    const rows = (templates?.items ?? []).map(item => row('templates', item.id, {
      title: item.name[lang] || item.name.en || item.id,
      detail: item.description[lang] || item.description.en,
      meta: [item.provider].filter(Boolean),
      target: route({ name: 'ui-library', params: { id: item.id }, query: { q } }),
    }))
    const total = templates?.total ?? 0
    if (rows.length && total > rows.length) rows.push(moreRow('templates', t('quickSearch.more.templates', { count: total }), { name: 'ui-library', query: { q } }))
    push('templates', total, rows)
  }

  return sections
}

/** 搜索框还空着时：最近搜过的词，选中即填回去再搜。 */
export function recentSection(queries: readonly string[]): QuickSearchSection[] {
  if (!queries.length) return []
  const rows = queries.map(q => row('recent', q, { title: q, detail: '', meta: [], target: { type: 'query', q } }))
  return [{ kind: 'recent', total: rows.length, rows, failed: false }]
}

/** 本机记着的最近搜过的词；读不出、格式不对都当没有。 */
export function parseRecentQueries(raw: string | null): string[] {
  if (!raw) return []
  try {
    const value: unknown = JSON.parse(raw)
    return Array.isArray(value)
      ? value.filter((q): q is string => typeof q === 'string' && searchableQuery(q) === q).slice(0, RECENT_QUERIES_MAX)
      : []
  } catch {
    return []
  }
}

/** 把这次的词放到最前，大小写不同的同一个词只留一份。 */
export function pushRecentQuery(queries: readonly string[], q: string): string[] {
  const key = q.toLowerCase()
  return [q, ...queries.filter(item => item.toLowerCase() !== key)].slice(0, RECENT_QUERIES_MAX)
}

export interface TextPart {
  text: string
  hit: boolean
}

/** 要在结果里标出来的词：按空格拆开，长的在前，免得短词先吃掉长词的一截。 */
export function highlightTerms(q: string): string[] {
  const terms = new Set(q.normalize('NFKC').toLowerCase().split(/\s+/).filter(Boolean))
  return [...terms].sort((a, b) => b.length - a.length)
}

const escapeRegExp = (value: string) => value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

/** 把文字切成命中与没命中的几段（不分大小写），交给模板逐段渲染，不拼 HTML。 */
export function highlight(text: string, terms: readonly string[]): TextPart[] {
  if (!text) return []
  if (!terms.length) return [{ text, hit: false }]
  const parts: TextPart[] = []
  let last = 0
  for (const match of text.matchAll(new RegExp(terms.map(escapeRegExp).join('|'), 'giu'))) {
    const start = match.index ?? 0
    if (start > last) parts.push({ text: text.slice(last, start), hit: false })
    parts.push({ text: match[0], hit: true })
    last = start + match[0].length
  }
  if (last < text.length) parts.push({ text: text.slice(last), hit: false })
  return parts
}
