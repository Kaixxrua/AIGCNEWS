import {
  ArrowUp,
  BookOpenText,
  Bot,
  Flame,
  Github,
  Heart,
  MessagesSquare,
  Newspaper,
  Star,
  ThumbsUp,
  type LucideIcon,
} from 'lucide-vue-next'
import { XLogoIcon } from '@/components/icons/XLogoIcon'
import { projectRollingGrowth } from '@/features/projects/projectPresentation'

export interface TopDoc {
  id?: number | string
  title?: string
  /** Repository short description, never README content. */
  description?: string
  description_zh?: string
  description_en?: string
  daily_star_growth?: number
  /** 热度 v8 的滚动 24h 星增（看板「+N」优先显示）；null 表示取不到窗口起点。 */
  rolling_24h_star_growth?: number | null
  rolling_24h_growth_source?: string | null
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
  /** 纯转贴的转贴者 handle（仅 X 转贴；卡片顶部据此标注「@xxx 转发了」，原作者仍为 author） */
  retweeted_by?: string | null
  /** 触发采集的关注账号显示名；转贴时与原作者 author_name 不同。 */
  followed_account_name?: string
  stars?: number
  language?: string
  feed_name?: string
  ai_score?: number
  image_url?: string | null
  hot_score?: number | null
  daily_growth_available?: boolean
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
  /** 采集期落库的 X 外链预览卡（仅 X 含外链推文；无卡/坏数据为空不渲染） */
  link_card?: TweetLinkCard | null
  /** 采集期落库的 X 自带中文翻译（仅 X 推文；zh 系界面语言优先展示） */
  translation_zh?: string
}

export interface TweetLinkCard {
  /** 目标页地址（采集期已展开 t.co；展开失败时保留 t.co 原值，整卡跳转目标） */
  url: string
  title: string
  description?: string
  /** 展示域名（X vanity_url，如 youtube.com） */
  domain?: string
  /** 卡片缩略图（pbs.twimg.com/card_img/ 镜像；缺失时渲染纯文本卡） */
  image_url?: string | null
  image_width?: number | null
  image_height?: number | null
  /** X 卡片类型（player/summary 等，仅元数据保留，渲染不区分） */
  card_type?: string
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
  /** 采集期落库的被引推文 X 中文翻译（zh 系界面语言优先展示；旧数据为空回退原文） */
  translation_zh?: string
}

export interface TweetMediaItem {
  type: 'photo' | 'video' | 'animated_gif'
  url: string
  /** Advertised lower bitrate MP4 for inline playback; url retains the original. */
  playback_url?: string
  width?: number
  height?: number
  /** 视频封面（服务端抽帧代理地址，仅 video/animated_gif；由 mediaItems 注入） */
  poster_url?: string
  /** 看板内联缩略图（twimg 按宽高选的约束框变体代理地址，仅 photo 且路径支持
      变体时由 mediaItems 注入）；item.url 同时换成 lightbox 大图变体 */
  thumb_url?: string
}

export interface Stats {
  total_documents?: number
  source_counts?: Record<string, number>
  github_library_total?: number
  github_enrichment?: {
    total: number
    succeeded: number
    failed: number
    unprocessable: number
    pending: number
  }
  registered_users?: number
  today_registered_users?: number
  user_count?: number
  today_new_documents?: number
  today_unique_visitors?: number
  today_visits?: number
  total_visits?: number
  mcp_total_calls?: number
  mcp_dsh_calls?: number
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
  { key: 'github',      labelKey: 'github',   icon: Github,     color: 'ink' },
  { key: 'arxiv',       labelKey: 'papers',   icon: BookOpenText, color: 'brand-blue' },
  { key: 'news',        labelKey: 'news',     icon: Newspaper,  color: 'brand-amber' },
  { key: 'producthunt', labelKey: 'products', icon: Bot,        color: 'brand-rose' },
  { key: 'hackernews',  labelKey: 'hn',       icon: MessagesSquare, color: 'brand-amber' },
  { key: 'x',           labelKey: 'x',        icon: XLogoIcon,  color: 'brand-blue' },
] as const

export type TabKey = (typeof TABS)[number]['key']

/* ── 分源榜单状态（/dashboard/top source_status）──────────────────────
   各源按自己的自然日界与定稿时刻揭榜：PT 源（arxiv/producthunt）次日
   CST 17:00，CST 源 01:00。tab 级徽章据此提示「收集中 / 已定稿」，
   与整榜静默期闸门（行为不变）并存。 */

export interface TabBoardStatus {
  isFinalized: boolean
  isEmbargoed: boolean
  dayBoundary: string
  finalizeHour: number | null
  isDisabled: boolean
}

export const getTabBoardStatus = (
  sourceStatus: Partial<Record<TabKey, {
    is_finalized?: boolean | null
    is_embargoed?: boolean | null
    day_boundary?: string | null
    finalize_hour?: number | null
    is_disabled?: boolean | null
  }>> | undefined,
  tab: TabKey,
): TabBoardStatus | null => {
  const status = sourceStatus?.[tab]
  if (!status) return null
  return {
    isFinalized: status.is_finalized ?? false,
    isEmbargoed: status.is_embargoed ?? false,
    dayBoundary: status.day_boundary ?? '',
    finalizeHour: typeof status.finalize_hour === 'number' ? status.finalize_hour : null,
    isDisabled: status.is_disabled ?? false,
  }
}

/** 定稿提示语（CST 次日整点揭榜）；无时刻信息返回 null 退化为纯文案 */
export const tabBoardStatusHint = (
  status: TabBoardStatus,
  translate: (key: string, params?: Record<string, unknown>) => string,
): string | null => {
  if (status.isFinalized) return translate('dashboard.tabFinalized')
  if (status.isEmbargoed && status.finalizeHour !== null) {
    return translate('dashboard.tabFinalizing', { time: `${status.finalizeHour}:00` })
  }
  return translate('dashboard.tabCollecting')
}

/** 榜单周期 wire 契约：前端已下线周/月榜切换（固定请求日榜），
    类型保留全量取值以描述后端仍接受的查询参数 */
export type PeriodKey = 'daily' | 'weekly' | 'monthly'

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

/** 看板「+N」：热度 v8 以滚动 24h 为准（首页不标「24h」），缺失时退回日增量；两者都没有时返回空串。 */
export const rankingGrowthLabel = (
  doc: TopDoc,
  t: (key: string, params?: Record<string, unknown>) => string,
  locale: string,
) => {
  const rolling = projectRollingGrowth(doc)
  if (rolling !== null) return `+${rolling.toLocaleString(locale)}`
  return doc.daily_growth_available && doc.daily_star_growth != null
    ? t('projects.todayGrowth', { count: doc.daily_star_growth.toLocaleString(locale) })
    : ''
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
    labelKey: 'github', key: 'github', dark: false,
    iconBg: 'bg-gray-100', iconColor: 'text-gray-600', numColor: 'text-gray-800',
    icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M9 19c-5 1.5-5-2.5-7-3m14 6v-3.87a3.37 3.37 0 00-.94-2.61c3.14-.35 6.44-1.54 6.44-7A5.44 5.44 0 0020 4.77 5.07 5.07 0 0019.91 1S18.73.65 16 2.48a13.38 13.38 0 00-7 0C6.27.65 5.09 1 5.09 1A5.07 5.07 0 005 4.77a5.44 5.44 0 00-1.5 3.78c0 5.42 3.3 6.61 6.44 7A3.37 3.37 0 009 18.13V22"/></svg>`,
  },
  {
    labelKey: 'papers', key: 'arxiv', dark: false,
    iconBg: 'bg-blue-50', iconColor: 'text-blue-500', numColor: 'text-blue-600',
    icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14,2 14,8 20,8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>`,
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
    labelKey: 'todayVisitors', key: 'today_visits', dark: false,
    iconBg: 'bg-purple-50', iconColor: 'text-purple-500', numColor: 'text-purple-600',
    icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>`,
  },
  {
    labelKey: 'totalVisitors', key: 'total_visits', dark: false,
    iconBg: 'bg-indigo-50', iconColor: 'text-indigo-500', numColor: 'text-indigo-600',
    icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 014 10 15.3 15.3 0 01-4 10 15.3 15.3 0 01-4-10 15.3 15.3 0 014-10z"/></svg>`,
  },
  {
    labelKey: 'newDocuments', key: 'today_new_documents', dark: false,
    iconBg: 'bg-teal-50', iconColor: 'text-teal-500', numColor: 'text-teal-600',
    icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="12" y1="18" x2="12" y2="12"/><line x1="9" y1="15" x2="15" y2="15"/></svg>`,
  },
]

const SOURCE_TAB_KEYS = new Set<TabKey>(TABS.map(tab => tab.key))

export const isSourceStatCard = (key: string): key is TabKey => SOURCE_TAB_KEYS.has(key as TabKey)
