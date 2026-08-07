import {
  ArrowUp,
  Circle,
  Code2,
  FileText,
  Flame,
  Heart,
  Newspaper,
  Rocket,
  Star,
  ThumbsUp,
  type LucideIcon,
} from 'lucide-vue-next'
import { XLogoIcon } from '@/components/icons/XLogoIcon'

export interface TopDoc {
  id?: number | string
  title?: string
  summary?: string
  score?: number
  raw_score?: number
  published_at?: string
  published_date?: string
  created_at?: string
  snapshot_date?: string
  source?: string
  url?: string
  author_avatar_url?: string
  /** 采集期落库的 X 账号昵称（display name；仅 X 推文，旧数据为空时回退展示 @handle） */
  author_name?: string
  stars?: number
  language?: string
  feed_name?: string
  ai_score?: number
  ai_reason?: string
  likes?: number
  downloads?: number
  pipeline_tag?: string
  source_channel?: string
  tags?: string[]
  votes?: number
  media?: TweetMediaItem[]
  /** 采集期落库的引用推文卡片（仅 X 引用推；被引删除/受保护时为空不渲染） */
  quote?: TweetQuote | null
  /** 采集期落库的 X 自带中文翻译（仅 X 推文；zh 系界面语言优先展示） */
  translation_zh?: string
}

export interface TweetQuote {
  /** 被引推文 canonical URL（卡片整卡跳转目标） */
  url: string
  /** 被引作者 handle（小写）与显示名 */
  author: string
  author_name: string
  author_avatar_url?: string
  /** 被引正文（采集期已剥媒体 t.co 尾巴并展开链接） */
  text: string
  media?: TweetMediaItem[]
  published_at?: string
}

export interface TweetMediaItem {
  type: 'photo' | 'video' | 'animated_gif'
  url: string
  width?: number
  height?: number
  /** 视频封面（服务端抽帧代理地址，仅 video/animated_gif；由 mediaItems 注入） */
  poster_url?: string
}

export interface Stats {
  total_documents?: number
  source_counts?: Record<string, number>
  registered_users?: number
  today_registered_users?: number
  user_count?: number
  today_new_documents?: number
  today_unique_visitors?: number
  mcp_total_calls?: number
}

const MODULE_KEYWORDS: Record<string, string[]> = {
  llm: ['llm', 'language model', 'gpt', 'llama', 'qwen', 'mistral', 'gemma', 'deepseek', 'moe', 'transformer', 'reasoning'],
  agents: ['agent', 'multi-agent', 'autonomous', 'tool use', 'planning', 'workflow', 'orchestration'],
  multimodal: ['multimodal', 'vision', 'vlm', 'image', 'video', 'audio', 'speech', 'ocr'],
  evaluation: ['benchmark', 'evaluation', 'dataset', 'alignment', 'safety'],
  engineering: ['inference', 'serving', 'quantization', 'distillation', 'vllm', 'edge', 'deployment'],
  rag: ['rag', 'retrieval', 'vector', 'embedding', 'knowledge'],
}

export const TABS = [
  { key: 'arxiv',       labelKey: 'papers',   icon: FileText,   color: 'brand-blue' },
  { key: 'github',      labelKey: 'github',   icon: Code2,      color: 'ink' },
  { key: 'news',        labelKey: 'news',     icon: Newspaper,  color: 'brand-amber' },
  { key: 'producthunt', labelKey: 'products', icon: Rocket,     color: 'brand-rose' },
  { key: 'hackernews',  labelKey: 'hn',       icon: Circle,     color: 'brand-amber' },
  { key: 'x',           labelKey: 'x',        icon: XLogoIcon,  color: 'brand-blue' },
] as const

export const PERIODS = [
  { key: 'daily' },
  { key: 'weekly' },
  { key: 'monthly' },
] as const

export const DAILY_ONLY_TABS = new Set(['news', 'producthunt', 'hackernews', 'x'])

export type TabKey = (typeof TABS)[number]['key']
export type PeriodKey = (typeof PERIODS)[number]['key']

export const getModuleTags = (doc: TopDoc): string[] => {
  const text = ((doc.title || '') + ' ' + (doc.summary || '')).toLowerCase()
  const tags: string[] = []
  for (const [tag, keywords] of Object.entries(MODULE_KEYWORDS)) {
    if (keywords.some(kw => text.includes(kw))) tags.push(tag)
  }
  return tags.slice(0, 3)
}

const SOURCE_CONFIG: Record<string, { label: string; dot: string; badge: string }> = {
  github:      { label: 'GitHub',  dot: 'bg-stone-400',  badge: 'bg-card text-stone-600 border border-stone-200' },
  arxiv:       { label: 'Arxiv',   dot: 'bg-stone-400',  badge: 'bg-card text-stone-600 border border-stone-200' },
  news:        { label: 'News',    dot: 'bg-stone-400',  badge: 'bg-card text-stone-600 border border-stone-200' },
  huggingface: { label: 'HF',      dot: 'bg-stone-400',  badge: 'bg-card text-stone-600 border border-stone-200' },
  producthunt: { label: 'PH',      dot: 'bg-stone-400',  badge: 'bg-card text-stone-600 border border-stone-200' },
  hackernews:  { label: 'HN',      dot: 'bg-stone-400',  badge: 'bg-card text-stone-600 border border-stone-200' },
  x:           { label: 'X',       dot: 'bg-stone-400',  badge: 'bg-card text-stone-600 border border-stone-200' },
}

export const getSourceConfig = (src?: string) =>
  SOURCE_CONFIG[src || ''] ?? { label: src || '?', dot: 'bg-stone-300', badge: 'bg-card text-stone-500 border border-stone-200' }

export const aiScoreDisplay = (score?: number) => {
  if (score === undefined || score === null) return null
  return `${score}/10`
}

export const scoreDisplay = (doc: TopDoc, formatNumber: (value: number) => string = String): { icon: LucideIcon; text: string; unitKey?: 'votes' | 'points' | 'likes' } => {
  if (doc.source === 'github')      return { icon: Star,     text: formatNumber(doc.stars ?? Math.round(doc.raw_score ?? doc.score ?? 0)) }
  if (doc.source === 'huggingface') return { icon: Heart,    text: formatNumber(Math.round(doc.raw_score ?? doc.likes ?? doc.score ?? 0)) }
  if (doc.source === 'news')        return { icon: Newspaper, text: `${doc.feed_name || 'News'}` }
  if (doc.source === 'producthunt') return { icon: ThumbsUp, text: formatNumber(Math.round(doc.raw_score ?? doc.votes ?? doc.score ?? 0)), unitKey: 'votes' }
  if (doc.source === 'hackernews')  return { icon: ArrowUp,  text: formatNumber(Math.round(doc.raw_score ?? doc.score ?? 0)), unitKey: 'points' }
  if (doc.source === 'x')           return { icon: Heart,    text: formatNumber(Math.round(doc.likes ?? doc.raw_score ?? doc.score ?? 0)), unitKey: 'likes' }
  return { icon: Flame, text: formatNumber(Math.round(doc.raw_score ?? doc.score ?? 0)) }
}

export const statCards = [
  {
    labelKey: 'total', key: 'total', dark: true,
    iconBg: 'bg-white/10', iconColor: 'text-gray-300', numColor: 'text-white',
    cardBg: 'bg-slate-800 border-slate-700',
    labelColor: 'text-slate-300',
    icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 014 10 15.3 15.3 0 01-4 10 15.3 15.3 0 01-4-10 15.3 15.3 0 014-10z"/></svg>`,
  },
  {
    labelKey: 'papers', key: 'arxiv', dark: false,
    iconBg: 'bg-blue-50', iconColor: 'text-blue-500', numColor: 'text-blue-600',
    icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14,2 14,8 20,8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>`,
  },
  {
    labelKey: 'github', key: 'github', dark: false,
    iconBg: 'bg-gray-100', iconColor: 'text-gray-600', numColor: 'text-gray-800',
    icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M9 19c-5 1.5-5-2.5-7-3m14 6v-3.87a3.37 3.37 0 00-.94-2.61c3.14-.35 6.44-1.54 6.44-7A5.44 5.44 0 0020 4.77 5.07 5.07 0 0019.91 1S18.73.65 16 2.48a13.38 13.38 0 00-7 0C6.27.65 5.09 1 5.09 1A5.07 5.07 0 005 4.77a5.44 5.44 0 00-1.5 3.78c0 5.42 3.3 6.61 6.44 7A3.37 3.37 0 009 18.13V22"/></svg>`,
  },
  {
    labelKey: 'news', key: 'news', dark: false,
    iconBg: 'bg-amber-50', iconColor: 'text-amber-500', numColor: 'text-amber-600',
    icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M4 22h16a2 2 0 002-2V4a2 2 0 00-2-2H8a2 2 0 00-2 2v16a2 2 0 01-2 2zm0 0a2 2 0 01-2-2v-9c0-1.1.9-2 2-2h2"/><line x1="10" y1="6" x2="18" y2="6"/><line x1="10" y1="10" x2="18" y2="10"/><line x1="10" y1="14" x2="14" y2="14"/></svg>`,
  },
  {
    labelKey: 'products', key: 'producthunt', dark: false,
    iconBg: 'bg-rose-50', iconColor: 'text-rose-500', numColor: 'text-rose-600',
    icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M21 16V8a2 2 0 00-1-1.73l-7-4a2 2 0 00-2 0l-7 4A2 2 0 003 8v8a2 2 0 001 1.73l7 4a2 2 0 002 0l7-4A2 2 0 0021 16z"/></svg>`,
  },
  {
    labelKey: 'hn', key: 'hackernews', dark: false,
    iconBg: 'bg-orange-50', iconColor: 'text-orange-500', numColor: 'text-orange-500',
    icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"/></svg>`,
  },
  {
    labelKey: 'x', key: 'x', dark: false,
    iconBg: 'bg-gray-100', iconColor: 'text-gray-800', numColor: 'text-gray-800',
    icon: `<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M18.901 1.153h3.68l-8.04 9.19L24 22.846h-7.406l-5.8-7.584-6.638 7.584H.474l8.6-9.83L0 1.154h7.594l5.243 6.932ZM17.61 20.644h2.039L6.486 3.24H4.298Z"/></svg>`,
  },
]

export const visitorCards = [
  {
    labelKey: 'users', key: 'user_count', dark: false,
    iconBg: 'bg-purple-50', iconColor: 'text-purple-500', numColor: 'text-purple-600',
    icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M17 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 00-3-3.87"/><path d="M16 3.13a4 4 0 010 7.75"/></svg>`,
  },
  {
    labelKey: 'newDocuments', key: 'today_new_documents', dark: false,
    iconBg: 'bg-teal-50', iconColor: 'text-teal-500', numColor: 'text-teal-600',
    icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="12" y1="18" x2="12" y2="12"/><line x1="9" y1="15" x2="15" y2="15"/></svg>`,
  },
]

const SOURCE_TAB_KEYS = new Set<TabKey>(TABS.map(tab => tab.key))

export const isSourceStatCard = (key: string): key is TabKey => SOURCE_TAB_KEYS.has(key as TabKey)
