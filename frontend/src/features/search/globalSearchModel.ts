import type { RouteLocationRaw } from 'vue-router'
import type { PaperItem } from '@/services/papers/paperApi'

export const GLOBAL_SEARCH_DEBOUNCE_MS = 300
export const GLOBAL_SEARCH_BLUR_DELAY_MS = 200
export const GLOBAL_SEARCH_RESULT_LIMIT = 20
export const GLOBAL_SEARCH_SUMMARY_LENGTH = 80

const SOURCE_LABEL_KEYS: Readonly<Record<string, string>> = {
  arxiv: 'search.paper',
  github: 'search.github',
  news: 'search.news',
  producthunt: 'search.producthunt',
  hackernews: 'search.hackernews',
  x: 'search.x',
}

export type GlobalSearchDestination =
  | { kind: 'route'; location: RouteLocationRaw }
  | { kind: 'external'; url: string }
  | { kind: 'none' }

export const getGlobalSearchDestination = (
  item: Pick<PaperItem, 'source' | 'id' | 'url'>,
): GlobalSearchDestination => {
  if (item.source === 'arxiv' && item.id) {
    return {
      kind: 'route',
      location: { name: 'paper-read', params: { id: item.id } },
    }
  }

  if (item.url) return { kind: 'external', url: item.url }
  return { kind: 'none' }
}

export const getSearchSourceLabelKey = (source?: string): string | null =>
  SOURCE_LABEL_KEYS[source || ''] ?? null

export const getSearchSummaryPreview = (summary?: string | null): string =>
  `${(summary || '').slice(0, GLOBAL_SEARCH_SUMMARY_LENGTH)}…`
