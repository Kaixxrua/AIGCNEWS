import type { StreamPhase } from '@/stores/chatStore'

export interface SourceFlat {
  id?: string
  score?: number
  source?: string
  title?: string
  url?: string
  published_date?: string
  metadata?: {
    title?: string
    url?: string
    source?: string
    source_type?: string
    node?: { id?: string }
  }
}

export const getSourceTitle = (src: unknown): string => {
  const s = src as SourceFlat
  return s?.title || s?.metadata?.title || s?.metadata?.node?.id || s?.id || 'Unknown Source'
}

export const getSourceType = (src: unknown): string => {
  const s = src as SourceFlat
  const channel = s?.source || s?.metadata?.source_type || s?.metadata?.source || ''
  if (channel === 'arxiv') return 'Arxiv'
  if (channel === 'github') return 'GitHub'
  if (channel === 'news') return 'News'
  if (channel === 'web') return 'Web'
  if (channel.toLowerCase().includes('neo4j') || channel.toLowerCase().includes('graph')) return 'Neo4j'
  if (channel.toLowerCase().includes('milvus') || channel.toLowerCase().includes('vector')) return 'Milvus'
  return channel || 'Unknown'
}

export const getSourceUrl = (src: unknown): string | null => {
  const s = src as SourceFlat
  return s?.url || s?.metadata?.url || null
}

export const sourceTypeBadgeClass = (type: string): string => {
  const t = type.toLowerCase()
  if (t === 'arxiv') return 'badge-arxiv'
  if (t === 'github') return 'badge-github'
  if (t === 'news') return 'badge-news'
  if (t === 'neo4j') return 'badge-neo4j'
  if (t === 'milvus') return 'badge-milvus'
  if (t === 'web') return 'badge-web'
  return 'badge-default'
}

export const getStreamPhaseLabel = (phase: StreamPhase): string => {
  switch (phase) {
    case 'searching': return 'searching'
    case 'reranking': return 'reranking'
    case 'answering': return 'answering'
    case 'error': return 'requestError'
    default: return ''
  }
}
