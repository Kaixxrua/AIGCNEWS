import type {
  GitHubProjectItem,
  GitHubProjectSort,
  ProjectFavoritePayload,
  ProjectScope,
} from '../../services/api'

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

export const projectSourceBadge = (project: GitHubProjectItem) => {
  if (isWebsite(project)) return '网页收藏'
  return project.is_recommended ? 'GitHub · 站长推荐' : 'GitHub'
}

export const projectLinkLabel = (project: GitHubProjectItem) => (
  isWebsite(project) ? '访问网站' : 'GitHub'
)

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

export const favoriteButtonLabel = (
  project: GitHubProjectItem,
  busy: boolean,
  isLoggedIn: boolean,
) => {
  if (busy) return '处理中'
  if (!project.is_favorited) return isLoggedIn ? '收藏' : '登录收藏'
  return isWebsite(project) && project.user_added ? '已加入' : '已收藏'
}

export const recommendButtonLabel = (project: GitHubProjectItem, busy: boolean) => {
  if (busy) return '处理中'
  return project.is_recommended ? '取消推荐' : '设为站长推荐'
}

export const fallbackProjectDescription = (project: GitHubProjectItem) => (
  isWebsite(project) ? '这个工具网页暂时没有中文简介。' : '这个项目暂时没有中文简介。'
)

export const projectDisplayTags = (
  project: GitHubProjectItem,
  isPersonalView: boolean,
): ProjectChip[] => {
  const result: ProjectChip[] = []
  const labels = new Set<string>()
  const pushChip = (chip: ProjectChip) => {
    const cleanLabel = chip.label.trim()
    if (!cleanLabel || labels.has(cleanLabel) || result.length >= 5) return
    labels.add(cleanLabel)
    result.push({ ...chip, label: cleanLabel })
  }

  if (project.subcategory_name && project.subcategory_slug) {
    pushChip({
      type: 'subcategory',
      label: project.subcategory_name,
      categorySlug: project.category_slug || '',
      value: project.subcategory_slug,
    })
  }
  if (project.category_name && project.category_slug) {
    pushChip({ type: 'category', label: project.category_name, value: project.category_slug })
  }
  const ignoredPersonalTags = new Set(['AI 工具', '网页收藏'])
  for (const tag of project.tags ?? []) {
    const label = String(tag).trim()
    if (isPersonalView && ignoredPersonalTags.has(label)) continue
    pushChip({ type: 'tag', label, value: label })
  }
  if (project.language) {
    pushChip({ type: 'language', label: project.language, value: project.language })
  }
  if (result.length) return result
  if (isPersonalView) return []
  const label = isWebsite(project) ? '网页收藏' : 'AI 项目'
  return [{ type: 'tag', label, value: label }]
}

export const formatProjectCount = (value: GitHubProjectItem['stars']) => {
  const numeric = Number(value ?? 0)
  if (!Number.isFinite(numeric)) return '0'

  return new Intl.NumberFormat('en', {
    notation: 'compact',
    maximumFractionDigits: 1,
  }).format(numeric)
}

export const formatProjectShortDate = (value: string | null | undefined) => {
  if (!value) return '已收藏'
  const date = new Date(value.endsWith('Z') || value.includes('+') ? value : `${value}Z`)
  if (Number.isNaN(date.getTime())) return '已收藏'
  return new Intl.DateTimeFormat('zh-CN', { month: '2-digit', day: '2-digit' }).format(date)
}

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

const formatGrowthObservedAt = (value: string | null | undefined) => {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date)
}

export const projectDailyGrowthTitle = (project: GitHubProjectItem) => {
  const source = projectDailyGrowthSource(project)
  if (source === 'snapshot_delta') {
    return `基于 ${project.previous_snapshot_date || '昨天'} → ${project.daily_growth_date || project.snapshot_date || '今天'} 的连续快照精确计算`
  }
  if (source === 'github_trending_daily') {
    const observedAt = formatGrowthObservedAt(project.daily_growth_observed_at)
    return `来自 GitHub Trending 日榜报告的 stars today${observedAt ? ` · ${observedAt} 采集` : ''}`
  }
  return '缺少连续快照和同日 GitHub Trending 日榜数据，今日增长暂按 0 计算'
}

export const shouldShowProjectHotScore = (
  project: GitHubProjectItem,
  sort: GitHubProjectSort,
  scope: ProjectScope,
) => !isWebsite(project) && (sort === 'hot' || scope === 'today')

export const formattedProjectHotScore = (project: GitHubProjectItem) => (
  projectHotScore(project).toFixed(1).replace(/\.0$/, '')
)
