import { formatLocaleCompactNumber, formatLocaleDate, formatLocaleRelativeDay } from '@/i18n/formatters'
import { estimateTextLines, textAdvancePx } from '@/utils/masonry'
import type { AppLocale } from '@/i18n'
import type {
  GitHubProjectItem,
  GitHubProjectSort,
  ProjectFavoritePayload,
  ProjectScope,
} from '@/services/projects/projectApi'

export type ProjectChip =
  | { type: 'subcategory'; label: string; categorySlug: string; value: string }
  | { type: 'category'; label: string; value: string }
  | { type: 'tag'; label: string; value: string }
  | { type: 'language'; label: string; value: string }

export const isWebsite = (project: GitHubProjectItem) => (
  project.source === 'website' || Boolean(project.website_id)
)

export const projectName = (project: GitHubProjectItem) => {
  const name = project.full_name || project.title || project.domain || String(project.repo_id ?? project.website_id ?? '')
  return name.trim()
}

// Keep owner/repository segments together when each segment fits the card.
export const projectNameParts = (project: GitHubProjectItem) => projectName(project).split(/(?<=\/)/)

export const projectUrl = (project: GitHubProjectItem) => {
  if (project.url) return project.url
  if (!isWebsite(project) && project.full_name) return `https://github.com/${project.full_name}`
  return ''
}

export const projectSourceBadgeKey = (project: GitHubProjectItem) => isWebsite(project) ? 'websiteFavorite' : project.is_recommended ? 'recommendedBadge' : ''

export const projectLinkLabelKey = (project: GitHubProjectItem) => isWebsite(project) ? 'visitWebsite' : ''

export const projectKey = (project: GitHubProjectItem) => (
  isWebsite(project)
    ? `website:${project.website_id}`
    : `github:${project.repo_id ?? project.full_name}`
)

export const projectLogoKey = (project: GitHubProjectItem) => {
  const url = isWebsite(project) ? (project.image_url || '') : ''
  return url ? `${projectKey(project)}:${url}` : ''
}

export const websiteLogoInitial = (project: GitHubProjectItem) => {
  const label = project.title || project.domain || projectName(project)
  return Array.from(label.trim())[0]?.toLocaleUpperCase() || 'W'
}

export const projectFavoritePayload = (project: GitHubProjectItem): ProjectFavoritePayload => {
  if (isWebsite(project)) return { source: 'website', website_id: project.website_id }
  return { source: 'github', repo_id: project.repo_id ?? project.full_name }
}

export const canFavoriteProject = (project: GitHubProjectItem) => (
  isWebsite(project) ? Boolean(project.website_id) : Boolean(project.repo_id || project.full_name)
)

export const canRecommendProject = (project: GitHubProjectItem, isAdmin: boolean) => (
  isAdmin && !isWebsite(project) && Boolean(project.repo_id || project.full_name)
)

export const canEditWebsiteProject = (project: GitHubProjectItem, isWebsiteOnlyView: boolean) => (
  isWebsiteOnlyView && isWebsite(project) && Boolean(project.user_added) && Boolean(project.website_id)
)

export const favoriteButtonLabelKey = (
  project: GitHubProjectItem,
  busy: boolean,
  isLoggedIn: boolean,
) => {
  if (busy) return 'common.processing'
  if (!project.is_favorited) return isLoggedIn ? 'projects.favorite' : 'projects.loginFavorite'
  return isWebsite(project) && project.user_added ? 'projects.added' : 'projects.favorited'
}

export const recommendButtonLabelKey = (project: GitHubProjectItem, busy: boolean) => {
  if (busy) return 'common.processing'
  return project.is_recommended ? 'projects.unrecommend' : 'projects.recommend'
}

type LocalizedName = {
  name?: string | null
  name_zh?: string | null
  name_en?: string | null
}

export const localizedProjectName = (value: LocalizedName | null | undefined, locale: AppLocale) => {
  const preferred = locale === 'zh-CN'
    ? [value?.name_zh, value?.name, value?.name_en]
    : [value?.name_en, value?.name, value?.name_zh]
  return preferred.find(label => typeof label === 'string' && label.trim())?.trim() || ''
}

export const localizedCategoryName = (
  value: LocalizedName | null | undefined,
  locale: AppLocale,
) => localizedProjectName(value, locale)

export type PersonalProjectTag = {
  value: string
  label: string
  label_zh?: string
  label_en?: string
  count: number
  tags_origin?: 'system' | 'user'
}

export const localizedPersonalTagLabel = (tag: PersonalProjectTag, locale: AppLocale) => {
  if (tag.tags_origin === 'user') return tag.value || tag.label
  const preferred = locale === 'zh-CN' ? tag.label_zh : tag.label_en
  return preferred?.trim() || tag.value || tag.label
}

export const projectDescription = (
  project: Pick<GitHubProjectItem, 'description' | 'description_zh' | 'description_en'>,
  locale: AppLocale,
  fallback: string,
) => {
  const preferred = locale === 'zh-CN'
    ? [project.description_zh, project.description_en, project.description]
    : [project.description_en, project.description, project.description_zh]
  return preferred.find(value => typeof value === 'string' && value.trim())?.trim() || fallback
}

export const projectCategoryName = (project: GitHubProjectItem, locale: AppLocale) => localizedProjectName({
  name: project.category_name,
  name_zh: project.category_name_zh,
  name_en: project.category_name_en,
}, locale)

export const projectSubcategoryName = (project: GitHubProjectItem, locale: AppLocale) => localizedProjectName({
  name: project.subcategory_name,
  name_zh: project.subcategory_name_zh,
  name_en: project.subcategory_name_en,
}, locale)

export const projectDisplayTags = (
  project: GitHubProjectItem,
  isPersonalView: boolean,
  locale: AppLocale = 'zh-CN',
  fallbackLabels: { project: string; website: string } = { project: 'AI 项目', website: '网页收藏' },
): ProjectChip[] => {
  const result: ProjectChip[] = []
  const labels = new Set<string>()
  const pushChip = (chip: ProjectChip) => {
    const cleanLabel = chip.label.trim()
    if (!cleanLabel || labels.has(cleanLabel) || result.length >= 5) return
    labels.add(cleanLabel)
    result.push({ ...chip, label: cleanLabel })
  }

  const subcategoryLabel = projectSubcategoryName(project, locale)
  const categoryLabel = projectCategoryName(project, locale)
  if (subcategoryLabel && project.subcategory_slug) {
    pushChip({
      type: 'subcategory',
      label: subcategoryLabel,
      categorySlug: project.category_slug || '',
      value: project.subcategory_slug,
    })
  }
  if (categoryLabel && project.category_slug) {
    pushChip({ type: 'category', label: categoryLabel, value: project.category_slug })
  }
  const ignoredPersonalTags = new Set(['AI 工具', '网页收藏'])
  const stableTags = project.tags ?? []
  const localizedTags = project.tags_origin === 'user'
    ? stableTags
    : locale === 'zh-CN'
      ? (project.tags_zh?.length ? project.tags_zh : stableTags)
      : (project.tags_en?.length ? project.tags_en : stableTags)
  for (const [index, tag] of stableTags.entries()) {
    const value = String(tag).trim()
    const label = String(localizedTags[index] ?? tag).trim()
    if (isPersonalView && ignoredPersonalTags.has(value)) continue
    pushChip({ type: 'tag', label, value })
  }
  if (project.language) {
    pushChip({ type: 'language', label: project.language, value: project.language })
  }
  if (result.length) return result
  if (isPersonalView) return []
  const website = isWebsite(project)
  const label = website ? fallbackLabels.website : fallbackLabels.project
  return [{ type: 'tag', label, value: website ? '网页收藏' : 'AI 项目' }]
}

export const formatProjectCount = (value: GitHubProjectItem['stars'], locale?: AppLocale) =>
  formatLocaleCompactNumber(Number(value ?? 0), locale)

export const formatProjectShortDate = (value: string | null | undefined, fallback: string, locale?: AppLocale) =>
  value ? formatLocaleDate(value, { month: '2-digit', day: '2-digit' }, locale) : fallback

export const formatProjectLastPush = (value: string | null | undefined, locale?: AppLocale, now?: Date) =>
  formatLocaleRelativeDay(value, locale, now)

export const projectLastPushTitle = (project: GitHubProjectItem, t: ProjectTranslate, locale?: AppLocale) => (
  project.pushed_at
    ? t('projects.lastPushTitle', { date: formatLocaleDate(project.pushed_at, { year: 'numeric', month: '2-digit', day: '2-digit' }, locale) })
    : ''
)

export const projectDailyGrowth = (project: GitHubProjectItem) => {
  const numeric = Number(project.daily_star_growth ?? 0)
  return Number.isFinite(numeric) && numeric > 0 ? numeric : 0
}

export const projectHotScore = (project: GitHubProjectItem) => {
  const numeric = Number(project.hot_score ?? project.score ?? 0)
  return Number.isFinite(numeric) && numeric > 0 ? numeric : 0
}

export const projectDailyGrowthSource = (project: GitHubProjectItem) => {
  if (project.daily_growth_source) return String(project.daily_growth_source)
  const available = (
    project.daily_growth_available === true
    || project.daily_growth_available === 1
    || project.daily_growth_available === '1'
    || project.daily_growth_available === 'true'
  )
  return available && project.previous_snapshot_date ? 'snapshot_delta' : 'unavailable'
}

const formatGrowthObservedAt = (value: string | null | undefined, locale?: AppLocale) => value ? formatLocaleDate(value, { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }, locale) : ''

export type ProjectTranslate = (key: string, params?: Record<string, unknown>) => string

export const projectDailyGrowthTitle = (project: GitHubProjectItem, t: ProjectTranslate, locale?: AppLocale) => {
  const source = projectDailyGrowthSource(project)
  if (source === 'snapshot_delta') {
    return t('projects.growthSnapshot', {
      from: project.previous_snapshot_date || t('projects.yesterday'),
      to: project.daily_growth_date || project.snapshot_date || t('projects.todayLabel'),
    })
  }
  if (source === 'github_trending_daily') {
    const observedAt = formatGrowthObservedAt(project.daily_growth_observed_at, locale)
    return t('projects.growthTrending', {
      observed: observedAt ? t('projects.observedAt', { date: observedAt }) : '',
    })
  }
  return t('projects.growthUnavailable')
}

export const shouldShowProjectHotScore = (
  project: GitHubProjectItem,
  _sort: GitHubProjectSort,
  _scope: ProjectScope,
) => !isWebsite(project)

export const formattedProjectHotScore = (project: GitHubProjectItem) => (
  projectHotScore(project).toFixed(1).replace(/\.0$/, '')
)

/* ─── 瀑布流估高（GitHubProjectsView 分列用） ─────────────────────────
 * 按 ProjectResultCard 模板结构逐项累加：来源徽标行、标题折行（按字宽）、
 * 域名行、描述折行、标签芯片贪心装行、统计行贪心装行。只需列间相对比较
 * 准确：描述与标题折行是估高主项，芯片/统计行的装行误差在列间相互抵消。
 * 返回值已把列间距（12px）折进每卡，可直接累加比较。 */

export interface ProjectCardHeightEstimateOptions {
  /** 个人视图会过滤兜底标签，影响芯片行数 */
  isPersonalView?: boolean
  /** 描述缺失时的本地化兜底文案（视图层 t() 解析后传入） */
  descriptionFallback?: string
  /** 无标签时的兜底芯片文案（视图层 t() 解析后传入） */
  genericTagLabels?: { project: string; website: string }
  /** 排序/范围：决定统计行是否多一项热度分 */
  sort?: GitHubProjectSort
  scope?: ProjectScope
}

const CARD_BORDER_PX = 2
const CARD_PADDING_PX = 36 // 上下 18×2
const CARD_SECTION_GAPS_PX = 14 * 3 // header / description / tags / stats
const CARD_MIN_HEIGHT_PX = 280 // .project-card__body min-height
const CARD_RAIL_WIDTH_PX = 40 // 侧边操作预留宽度
const BADGE_ROW_PX = 32 // 来源 24px + 标题 margin-top 8px
const TITLE_LINE_PX = 24.3 // 18px × 1.35
const DOMAIN_ROW_PX = 18 // 12px 行 + margin-top 4
const DESC_LINE_PX = 23.8 // 14px × 1.7
const CHIP_GAP_PX = 6
const CHIP_TEXT_PADDING_PX = 14 // 左右 padding 12 + 边框 2
const CHIP_LINE_PX = 15.95 // 11px × 1.45
const CHIP_VERTICAL_PADDING_PX = 4
const STATS_HEAD_PX = 13 // padding-top 12 + 上边框 1
const STATS_LINE_PX = 18 // 12px 字 / 14px 图标取整
const STATS_GAP_PX = 10

/** 芯片几何：标签文本在芯片内折行（窄列常见 2 行芯片）；装行宽度封顶容器宽 */
const chipGeometry = (label: string, contentWidth: number): { width: number; height: number } => {
  const textWidth = textAdvancePx(label, 11)
  const innerWidth = Math.max(40, contentWidth - CHIP_TEXT_PADDING_PX)
  const lines = Math.max(1, Math.ceil(textWidth / innerWidth))
  return {
    width: Math.min(textWidth + CHIP_TEXT_PADDING_PX, contentWidth),
    height: Math.max(20, lines * CHIP_LINE_PX + CHIP_VERTICAL_PADDING_PX),
  }
}

/** flex-wrap 近似装行：按容器宽贪心换行，行高取行内最高件 */
const packRowHeights = (items: { width: number; height: number }[], containerWidth: number, gapPx: number): number => {
  if (!items.length) return 0
  let total = 0
  let rowWidth = 0
  let rowHeight = 0
  for (const item of items) {
    if (rowWidth > 0 && rowWidth + gapPx + item.width > containerWidth) {
      total += rowHeight + gapPx
      rowWidth = item.width
      rowHeight = item.height
    } else {
      rowWidth = rowWidth > 0 ? rowWidth + gapPx + item.width : item.width
      rowHeight = Math.max(rowHeight, item.height)
    }
  }
  return total + rowHeight
}

/** 统计行单项宽度近似：图标 14 + 间距 5 + 文本按 12px 字宽 */
const statsItemWidthPx = (text: string): number => 19 + textAdvancePx(text, 12)

export const estimateProjectCardHeight = (
  project: GitHubProjectItem,
  columnWidth: number,
  locale: AppLocale = 'zh-CN',
  options: ProjectCardHeightEstimateOptions = {},
): number => {
  const cardWidth = Math.max(200, columnWidth - CARD_RAIL_WIDTH_PX)
  const contentWidth = Math.max(80, cardWidth - CARD_BORDER_PX - CARD_PADDING_PX)
  let height = CARD_BORDER_PX + CARD_PADDING_PX + CARD_SECTION_GAPS_PX
  // 头部：徽标 + 标题折行（徽标+标题恒高于 42px logo，logo 不主导行高）
  height += BADGE_ROW_PX + packRowHeights(projectNameParts(project).map(part => ({
    width: Math.min(textAdvancePx(part, 18), contentWidth),
    height: Math.max(1, estimateTextLines(part, contentWidth, 18)) * TITLE_LINE_PX,
  })), contentWidth, 0)
  if (isWebsite(project) && project.domain) height += DOMAIN_ROW_PX
  const description = projectDescription(project, locale, options.descriptionFallback ?? '')
  height += estimateTextLines(description, contentWidth, 14) * DESC_LINE_PX
  const chips = projectDisplayTags(
    project,
    options.isPersonalView ?? false,
    locale,
    options.genericTagLabels ?? { project: 'AI 项目', website: '网页收藏' },
  )
  const tagListWidth = chips.length > 3 ? contentWidth - 24 - CHIP_GAP_PX : contentWidth
  const visibleChips = chips.slice(0, 3).map((chip) => chipGeometry(chip.label, tagListWidth))
  height += packRowHeights(visibleChips, tagListWidth, CHIP_GAP_PX)
  const stats: number[] = []
  if (isWebsite(project)) {
    stats.push(statsItemWidthPx(project.domain || 'website'))
    stats.push(statsItemWidthPx('收录 00/00'))
  } else {
    // 实测 zh 统计行宽度标定（'45.6k stars'/'今日 +123'/'热度 42'/'1.2k forks'/'3 天前'），
    // 窄列通常 3 行；en 文案量级相当，列间误差相互抵消
    stats.push(statsItemWidthPx('00.0k stars'))
    stats.push(statsItemWidthPx('今日 +000'))
    if (options.sort && options.scope && shouldShowProjectHotScore(project, options.sort, options.scope)) stats.push(statsItemWidthPx('热度 00'))
    stats.push(statsItemWidthPx('0.0k forks'))
    if (project.pushed_at) stats.push(statsItemWidthPx('0 天前'))
  }
  height += STATS_HEAD_PX + packRowHeights(
    stats.map((width) => ({ width, height: STATS_LINE_PX })),
    contentWidth,
    STATS_GAP_PX,
  )
  return Math.max(height, CARD_MIN_HEIGHT_PX) + 12 // 列间距 gap 折进每卡
}
