import { api } from '@/services/http/apiClient'
import type {
  SearchBriefingWire,
  SearchGroupWire,
  SearchPaperWire,
  SearchProjectWire,
  SearchTweetWire,
  SearchWireResponse,
} from './searchContracts'

export const QUICK_SEARCH_GROUPS = ['projects', 'papers', 'briefings', 'tweets'] as const
export type QuickSearchGroupName = typeof QUICK_SEARCH_GROUPS[number]

/** 每组默认取几条；后端上限 8。 */
export const QUICK_SEARCH_LIMIT = 5

export interface QuickSearchGroup<T> {
  total: number
  items: T[]
}

export interface QuickSearchProject {
  fullName: string
  url: string
  description: string
  descriptionZh: string
  descriptionEn: string
  stars: number
  language: string
}

export interface QuickSearchPaper {
  id: string
  title: string
  summary: string
  date: string
  /** 前几位作者；authorCount 是全部作者数。 */
  authors: string[]
  authorCount: number
}

export interface QuickSearchBriefing {
  date: string
  type: string
  title: string
  lead: string
  snippet: string
}

export interface QuickSearchTweet {
  id: string
  text: string
  url: string
  author: string
  date: string
}

export interface QuickSearchResult {
  q: string
  projects: QuickSearchGroup<QuickSearchProject> | null
  papers: QuickSearchGroup<QuickSearchPaper> | null
  briefings: QuickSearchGroup<QuickSearchBriefing> | null
  /** X 源关闭时没有这一组。 */
  tweets: QuickSearchGroup<QuickSearchTweet> | null
  failed: QuickSearchGroupName[]
}

const text = (value: unknown): string => (typeof value === 'string' ? value : '')
const count = (value: unknown): number => (typeof value === 'number' && Number.isFinite(value) && value > 0 ? Math.floor(value) : 0)

/** 缺了的组为 null；条目缺关键字段的丢掉；总数不少于实际给出的条数。 */
function group<W, T>(wire: SearchGroupWire<W> | null | undefined, map: (item: W) => T | null): QuickSearchGroup<T> | null {
  if (!wire || typeof wire !== 'object') return null
  const items = (Array.isArray(wire.items) ? wire.items : [])
    .map(item => (item && typeof item === 'object' ? map(item) : null))
    .filter((item): item is T => item !== null)
  return { total: Math.max(count(wire.total), items.length), items }
}

const mapProject = (item: SearchProjectWire): QuickSearchProject | null => {
  const fullName = text(item.full_name)
  if (!fullName) return null
  return {
    fullName,
    url: text(item.url),
    description: text(item.description),
    descriptionZh: text(item.description_zh),
    descriptionEn: text(item.description_en),
    stars: count(item.stars),
    language: text(item.language),
  }
}

const mapPaper = (item: SearchPaperWire): QuickSearchPaper | null => {
  const id = text(item.id)
  if (!id) return null
  const authors = Array.isArray(item.authors) ? item.authors.filter((name): name is string => typeof name === 'string' && name.trim() !== '') : []
  return {
    id,
    title: text(item.title),
    summary: text(item.summary),
    date: text(item.date),
    authors,
    authorCount: Math.max(count(item.author_count), authors.length),
  }
}

const mapBriefing = (item: SearchBriefingWire): QuickSearchBriefing | null => {
  const date = text(item.date)
  const type = text(item.type)
  if (!/^\d{4}-\d{2}-\d{2}$/.test(date) || !type) return null
  return { date, type, title: text(item.title), lead: text(item.lead), snippet: text(item.snippet) }
}

const mapTweet = (item: SearchTweetWire): QuickSearchTweet | null => {
  const id = text(item.id)
  const url = text(item.url)
  if (!id && !url) return null
  return { id, text: text(item.text), url, author: text(item.author), date: text(item.date) }
}

const isGroupName = (name: unknown): name is QuickSearchGroupName =>
  typeof name === 'string' && (QUICK_SEARCH_GROUPS as readonly string[]).includes(name)

export const fetchQuickSearch = async (
  q: string,
  { locale, limit = QUICK_SEARCH_LIMIT, signal }: { locale: string; limit?: number; signal?: AbortSignal },
): Promise<QuickSearchResult> => {
  const response = await api.get<SearchWireResponse>('/search', { params: { q, limit, locale }, signal })
  const data = response.data && typeof response.data === 'object' ? response.data : {}
  const groups = data.groups && typeof data.groups === 'object' ? data.groups : {}
  return {
    q: text(data.q) || q,
    projects: group(groups.projects, mapProject),
    papers: group(groups.papers, mapPaper),
    briefings: group(groups.briefings, mapBriefing),
    tweets: group(groups.tweets, mapTweet),
    failed: Array.isArray(data.failed) ? data.failed.filter(isGroupName) : [],
  }
}
