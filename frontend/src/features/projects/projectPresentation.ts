import { formatLocaleCompactNumber, formatLocaleDate } from '@/i18n/formatters'
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
  project: GitHubProjectItem,
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
  sort: GitHubProjectSort,
  scope: ProjectScope,
) => !isWebsite(project) && (sort === 'hot' || scope === 'today')

export const formattedProjectHotScore = (project: GitHubProjectItem) => (
  projectHotScore(project).toFixed(1).replace(/\.0$/, '')
)
