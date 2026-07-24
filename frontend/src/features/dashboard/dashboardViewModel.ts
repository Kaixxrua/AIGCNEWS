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
} from 'lucide-vue-next'

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
}

export interface Stats {
  total_documents?: number
  source_counts?: Record<string, number>
  registered_users?: number
  today_registered_users?: number
  user_count?: number
  today_new_documents?: number
  today_unique_visitors?: number
}

const MODULE_KEYWORDS: Record<string, string[]> = {
  '大模型': ['llm', 'language model', 'gpt', 'llama', 'qwen', 'mistral', 'gemma', 'deepseek', 'moe', 'transformer', 'reasoning'],
  '智能体': ['agent', 'multi-agent', 'autonomous', 'tool use', 'planning', 'workflow', 'orchestration'],
  '多模态': ['multimodal', 'vision', 'vlm', 'image', 'video', 'audio', 'speech', 'ocr'],
  '评测':   ['benchmark', 'evaluation', 'dataset', 'alignment', 'safety'],
  '工程':   ['inference', 'serving', 'quantization', 'distillation', 'vllm', 'edge', 'deployment'],
  'RAG':    ['rag', 'retrieval', 'vector', 'embedding', 'knowledge'],
}

export const TABS = [
  { key: 'arxiv',       label: 'Papers',   icon: FileText,   color: 'brand-blue' },
  { key: 'github',      label: 'Code',     icon: Code2,      color: 'ink' },
  { key: 'news',        label: 'News',     icon: Newspaper,  color: 'brand-amber' },
  { key: 'producthunt', label: 'Products', icon: Rocket,     color: 'brand-rose' },
  { key: 'hackernews',  label: 'HN',       icon: Circle,     color: 'brand-amber' },
] as const

export const PERIODS = [
  { key: 'daily',   label: '日榜' },
  { key: 'weekly',  label: '周榜' },
  { key: 'monthly', label: '月榜' },
] as const

export const DAILY_ONLY_TABS = new Set(['news', 'producthunt', 'hackernews'])

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
  github:      { label: 'GitHub',  dot: 'bg-stone-400',  badge: 'bg-white text-stone-600 border border-stone-200' },
  arxiv:       { label: 'Arxiv',   dot: 'bg-stone-400',  badge: 'bg-white text-stone-600 border border-stone-200' },
  news:        { label: 'News',    dot: 'bg-stone-400',  badge: 'bg-white text-stone-600 border border-stone-200' },
  huggingface: { label: 'HF',      dot: 'bg-stone-400',  badge: 'bg-white text-stone-600 border border-stone-200' },
  producthunt: { label: 'PH',      dot: 'bg-stone-400',  badge: 'bg-white text-stone-600 border border-stone-200' },
  hackernews:  { label: 'HN',      dot: 'bg-stone-400',  badge: 'bg-white text-stone-600 border border-stone-200' },
}

export const getSourceConfig = (src?: string) =>
  SOURCE_CONFIG[src || ''] ?? { label: src || '?', dot: 'bg-stone-300', badge: 'bg-white text-stone-500 border border-stone-200' }

export const aiScoreDisplay = (score?: number) => {
  if (score === undefined || score === null) return null
  return `${score}/10`
}

export const scoreDisplay = (doc: TopDoc): { icon: any; text: string } => {
  if (doc.source === 'github')      return { icon: Star,     text: `${doc.stars ?? Math.round(doc.raw_score ?? doc.score ?? 0)}` }
  if (doc.source === 'huggingface') return { icon: Heart,    text: `${Math.round(doc.raw_score ?? doc.likes ?? doc.score ?? 0)}` }
  if (doc.source === 'news')        return { icon: Newspaper, text: `${doc.feed_name || '新闻'}` }
  if (doc.source === 'producthunt') return { icon: ThumbsUp, text: `${Math.round(doc.raw_score ?? doc.votes ?? doc.score ?? 0)} votes` }
  if (doc.source === 'hackernews')  return { icon: ArrowUp,  text: `${Math.round(doc.raw_score ?? doc.score ?? 0)} pts` }
  return { icon: Flame, text: `${Math.round(doc.raw_score ?? doc.score ?? 0)}` }
}

export const statCards = [
  {
    label: 'Total', key: 'total', dark: true,
    iconBg: 'bg-white/10', iconColor: 'text-gray-300', numColor: 'text-white',
    cardBg: 'bg-slate-800 border-slate-700',
    labelColor: 'text-slate-300',
    icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 014 10 15.3 15.3 0 01-4 10 15.3 15.3 0 01-4-10 15.3 15.3 0 014-10z"/></svg>`,
  },
  {
    label: 'Papers', key: 'arxiv', dark: false,
    iconBg: 'bg-blue-50', iconColor: 'text-blue-500', numColor: 'text-blue-600',
    icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14,2 14,8 20,8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>`,
  },
  {
    label: 'GitHub', key: 'github', dark: false,
    iconBg: 'bg-gray-100', iconColor: 'text-gray-600', numColor: 'text-gray-800',
    icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M9 19c-5 1.5-5-2.5-7-3m14 6v-3.87a3.37 3.37 0 00-.94-2.61c3.14-.35 6.44-1.54 6.44-7A5.44 5.44 0 0020 4.77 5.07 5.07 0 0019.91 1S18.73.65 16 2.48a13.38 13.38 0 00-7 0C6.27.65 5.09 1 5.09 1A5.07 5.07 0 005 4.77a5.44 5.44 0 00-1.5 3.78c0 5.42 3.3 6.61 6.44 7A3.37 3.37 0 009 18.13V22"/></svg>`,
  },
  {
    label: 'News', key: 'news', dark: false,
    iconBg: 'bg-amber-50', iconColor: 'text-amber-500', numColor: 'text-amber-600',
    icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M4 22h16a2 2 0 002-2V4a2 2 0 00-2-2H8a2 2 0 00-2 2v16a2 2 0 01-2 2zm0 0a2 2 0 01-2-2v-9c0-1.1.9-2 2-2h2"/><line x1="10" y1="6" x2="18" y2="6"/><line x1="10" y1="10" x2="18" y2="10"/><line x1="10" y1="14" x2="14" y2="14"/></svg>`,
  },
  {
    label: 'Products', key: 'producthunt', dark: false,
    iconBg: 'bg-rose-50', iconColor: 'text-rose-500', numColor: 'text-rose-600',
    icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M21 16V8a2 2 0 00-1-1.73l-7-4a2 2 0 00-2 0l-7 4A2 2 0 003 8v8a2 2 0 001 1.73l7 4a2 2 0 002 0l7-4A2 2 0 0021 16z"/></svg>`,
  },
  {
    label: 'HN', key: 'hackernews', dark: false,
    iconBg: 'bg-orange-50', iconColor: 'text-orange-500', numColor: 'text-orange-500',
    icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"/></svg>`,
  },
]

export const visitorCards = [
  {
    label: '用户数', key: 'user_count', dark: false,
    iconBg: 'bg-purple-50', iconColor: 'text-purple-500', numColor: 'text-purple-600',
    icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M17 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 00-3-3.87"/><path d="M16 3.13a4 4 0 010 7.75"/></svg>`,
  },
  {
    label: '新增文档数', key: 'today_new_documents', dark: false,
    iconBg: 'bg-teal-50', iconColor: 'text-teal-500', numColor: 'text-teal-600',
    icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="12" y1="18" x2="12" y2="12"/><line x1="9" y1="15" x2="15" y2="15"/></svg>`,
  },
]

const SOURCE_TAB_KEYS = new Set<TabKey>(TABS.map(tab => tab.key))

export const isSourceStatCard = (key: string): key is TabKey => SOURCE_TAB_KEYS.has(key as TabKey)
