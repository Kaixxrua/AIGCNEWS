/* eslint-disable @typescript-eslint/no-explicit-any -- API 边界 normalizer 基线：
   响应载荷先按 any 归一化再收窄到导出类型，随后端契约类型化逐步移除。 */
import { api } from '@/services/http/apiClient'
import { i18n } from '@/i18n'
import type { ProjectAssessment } from '@/features/projects/projectAssessment'

const TOOL_WEBSITE_ADD_TIMEOUT = 120_000

export type GitHubProjectSort = 'hot' | 'stars' | 'updated' | 'recent' | 'name' | 'relevance'
export type ProjectSource = 'all' | 'github' | 'website'
export type ProjectViewSource = ProjectSource | 'favorites'
export type ProjectScope = 'all' | 'today' | 'recommended' | 'screened'

export interface GitHubProjectSubcategory {
  slug: string
  name: string
  name_zh?: string
  name_en?: string
  count: number
}

export interface GitHubProjectCategory {
  slug: string
  name: string
  name_zh?: string
  name_en?: string
  count: number
  kind?: 'scope' | 'category'
  scope?: ProjectScope
  children?: GitHubProjectSubcategory[]
}

export interface GitHubProjectItem {
  id?: string | null
  source?: ProjectSource | string
  repo_id?: string | number | null
  website_id?: string | number | null
  full_name: string
  title?: string | null
  url?: string | null
  domain?: string | null
  image_url?: string | null
  description?: string | null
  description_zh?: string | null
  description_en?: string | null
  assessment?: ProjectAssessment | null
  category_slug?: string | null
  category_name?: string | null
  category_name_zh?: string | null
  category_name_en?: string | null
  subcategory_slug?: string | null
  subcategory_name?: string | null
  subcategory_name_zh?: string | null
  subcategory_name_en?: string | null
  tags?: string[]
  tags_zh?: string[]
  tags_en?: string[]
  tags_origin?: 'system' | 'user'
  language?: string | null
  topics?: string[]
  stars?: number | string | null
  forks?: number | string | null
  watchers?: number | string | null
  open_issues?: number | string | null
  created_at?: string | null
  pushed_at?: string | null
  first_seen_at?: string | null
  last_seen_at?: string | null
  last_snapshot_at?: string | null
  availability_status?: 'active' | 'not_found' | string
  snapshot_date?: string | null
  captured_at?: string | null
  rank_in_period?: number | string | null
  raw_score?: number | string | null
  score?: number | string | null
  daily_star_growth?: number | string | null
  daily_growth_available?: boolean | number | string | null
  daily_growth_source?: 'snapshot_delta' | 'github_trending_daily' | 'creation_baseline' | 'unavailable' | string | null
  daily_growth_observed_at?: string | null
  /** 热度 v8 的滚动 24h 星增；null 表示取不到窗口起点。 */
  rolling_24h_star_growth?: number | string | null
  rolling_24h_growth_source?: 'rolling_window' | 'creation_interpolated' | 'since_creation' | string | null
  rolling_24h_observed_at?: string | null
  daily_growth_date?: string | null
  previous_snapshot_date?: string | null
  hot_score?: number | string | null
  scale_corrected_growth_score?: number | string | null
  growth_acceleration_score?: number | string | null
  absolute_growth_score?: number | string | null
  maintenance_activity_score?: number | string | null
  community_engagement_score?: number | string | null
  confidence?: number | string | null
  is_favorited?: boolean
  favorited_at?: string | null
  is_recommended?: boolean
  recommended_at?: string | null
  user_added?: boolean
  user_added_at?: string | null
}

export interface GitHubProjectsResponse {
  items: GitHubProjectItem[]
  total: number
  page: number
  page_size: number
  has_next: boolean
  min_stars: number
  scope?: ProjectScope
  category?: string
  subcategory?: string
  q?: string
  tag?: string
  sort?: GitHubProjectSort
  source?: ProjectSource | string
}

export interface GitHubProjectCategoriesResponse {
  items: GitHubProjectCategory[]
  total: number
  today_count?: number
  recommended_count?: number
  min_stars: number
  source?: ProjectSource | string
}

export interface GitHubProjectTag {
  /** Stable legacy tag value used by the `tag=` filter. */
  value: string
  /** Backward-compatible stable label. */
  label: string
  label_zh?: string
  label_en?: string
  count: number
  tags_origin?: 'system' | 'user'
}

export interface GitHubProjectTagsResponse {
  items: GitHubProjectTag[]
  total: number
  source?: ProjectSource | string
}

export interface GitHubProjectTrendPoint {
  date: string
  stars: number
  /** 那天的可信日增；null 表示缺前一天快照、算不出来，不是 0。 */
  gain: number | null
}

export interface GitHubProjectTrend {
  points: GitHubProjectTrendPoint[]
  /** 昨日热榜名次（前 200），不在榜上为 null；只有带 ranks 请求时才可信。 */
  previous_rank?: number | null
}

export interface GitHubProjectTrendsResponse {
  /** 窗口最后一天：今天的指标还没落库时是昨天。 */
  metric_date: string
  /** 名次对照的那一天；没带 ranks 请求时为 null。 */
  previous_date: string | null
  days: number
  items: Record<string, GitHubProjectTrend>
}

export interface ProjectTrendsOptions {
  days?: number
  ranks?: boolean
  signal?: AbortSignal
}

export interface GitHubProjectPeekCommit {
  sha: string
  /** 提交信息的第一行；可能为空 */
  message: string
  /** GitHub 账号；提交没关联账号时是 git 作者名，也可能为空 */
  author: string
  committed_at: string
  /** 这次提交在 GitHub 上的页面 */
  url: string
}

export interface GitHubProjectPeek {
  repo_id: string
  /** ok：读到了 GitHub（可能是早些时候存下的一份）；unavailable：读不到 GitHub，也没有存着的 */
  status: 'ok' | 'unavailable'
  has_readme: boolean
  /** README 开头几段的纯文本；README 开头没有成段的文字时为空 */
  readme: string[]
  /** README 在这几段之后还有 */
  readme_more: boolean
  /** 默认分支最近一次提交；空仓库或读不到时为 null */
  commit: GitHubProjectPeekCommit | null
}

export interface ToolWebsiteAddResponse {
  status: string
  message: string
  duplicate: boolean
  item?: GitHubProjectItem | null
}

export interface ToolWebsiteDeleteResponse {
  status: string
  message: string
  deleted: boolean
  website_id: number
}

export interface PersonalWebsiteQuota {
  tier: 'free' | 'member'
  unlimited: boolean
  limit: number | null
  used: number
  remaining: number | null
  window_seconds: number
  reset_at: string | null
}

export interface ToolWebsiteUpdatePayload {
  title: string
  description?: string
  description_zh: string
  description_en?: string
  category_slug: string
  subcategory_slug?: string
  tags?: string[]
  image_url?: string | null
}

export interface ToolWebsiteUpdateResponse {
  status: string
  message: string
  item?: GitHubProjectItem | null
}

export interface ProjectFavoritePayload {
  source: 'github' | 'website'
  repo_id?: string | number | null
  website_id?: string | number | null
}

export interface ProjectFavoriteResponse {
  status: string
  message: string
  source: 'github' | 'website' | string
  repo_id?: string | number | null
  website_id?: string | number | null
  is_favorited: boolean
  favorited_at?: string | null
  deleted?: boolean
}

export interface GitHubProjectRecommendPayload {
  repo_id?: string | number | null
  full_name?: string | null
}

export interface GitHubProjectRecommendResponse {
  status: string
  message: string
  repo_id: string
  full_name: string
  is_recommended: boolean
  recommended_at?: string | null
  removed?: boolean
}

export interface ProjectTaxonomyItem {
  slug: string
  name: string
  name_zh?: string
  name_en?: string
  children: Array<{ slug: string; name: string; name_zh: string; name_en: string }>
}

export interface ProjectTaxonomyResponse {
  items: ProjectTaxonomyItem[]
}

export interface ManualToolWebsitePayload {
  url: string
  title: string
  description_zh: string
  description_en?: string
  category_slug: string
  subcategory_slug?: string
  tags?: string[]
}

export interface ProjectListParams {
  source?: ProjectSource
  scope?: ProjectScope
  category?: string
  subcategory?: string
  q?: string
  language?: string
  tag?: string
  page?: number
  page_size?: number
  sort?: GitHubProjectSort
}

function normalizeProjectsResponse(data: any, params?: ProjectListParams): GitHubProjectsResponse {
  return {
    items: Array.isArray(data?.items) ? data.items : [],
    total: Number(data?.total ?? 0),
    page: Number(data?.page ?? params?.page ?? 1),
    page_size: Number(data?.page_size ?? params?.page_size ?? 24),
    has_next: Boolean(data?.has_next),
    min_stars: Number(data?.min_stars ?? 500),
    scope: data?.scope ?? params?.scope ?? 'all',
    category: data?.category ?? params?.category ?? '',
    subcategory: data?.subcategory ?? params?.subcategory ?? '',
    q: data?.q ?? params?.q ?? '',
    tag: params?.tag ?? '',
    sort: data?.sort ?? params?.sort ?? 'stars',
    source: data?.source ?? params?.source ?? 'all',
  }
}

export async function fetchProjects(params?: ProjectListParams): Promise<GitHubProjectsResponse> {
  const res = await api.get('/projects', { params })
  return normalizeProjectsResponse(res.data, params)
}

export async function fetchMyProjectCollection(params?: ProjectListParams): Promise<GitHubProjectsResponse> {
  const res = await api.get('/projects/me/collection', { params })
  return normalizeProjectsResponse(res.data, params)
}

function normalizeProjectCategoriesResponse(data: any, source: ProjectSource): GitHubProjectCategoriesResponse {
  return {
    items: Array.isArray(data?.items) ? data.items : [],
    total: Number(data?.total ?? 0),
    today_count: Number(data?.today_count ?? 0),
    recommended_count: Number(data?.recommended_count ?? 0),
    min_stars: Number(data?.min_stars ?? 500),
    source: data?.source ?? source,
  }
}

export async function fetchProjectCategories(
  source: ProjectSource = 'all',
): Promise<GitHubProjectCategoriesResponse> {
  const res = await api.get('/projects/categories', { params: { source } })
  return normalizeProjectCategoriesResponse(res.data, source)
}

const finiteOrNull = (value: any): number | null => {
  if (value === null || value === undefined || value === '') return null
  const number = Number(value)
  return Number.isFinite(number) ? number : null
}

function normalizeProjectTrendsResponse(data: any, days: number): GitHubProjectTrendsResponse {
  const items: Record<string, GitHubProjectTrend> = {}
  const raw = data?.items && typeof data.items === 'object' ? data.items : {}
  for (const [repoId, value] of Object.entries<any>(raw)) {
    const points: GitHubProjectTrendPoint[] = Array.isArray(value?.points)
      ? value.points
          .map((point: any) => ({
            date: String(point?.date ?? ''),
            stars: Number(point?.stars ?? 0) || 0,
            gain: finiteOrNull(point?.gain),
          }))
          .filter((point: GitHubProjectTrendPoint) => point.date)
      : []
    items[repoId] = { points, previous_rank: finiteOrNull(value?.previous_rank) }
  }
  return {
    metric_date: String(data?.metric_date ?? ''),
    previous_date: data?.previous_date ? String(data.previous_date) : null,
    days: Number(data?.days ?? days) || days,
    items,
  }
}

/** 一页榜单的近 N 天星标与日增；ranks 时附昨日热榜名次（今日热门用来标升降）。 */
export async function fetchProjectTrends(
  repoIds: readonly string[],
  { days = 14, ranks = false, signal }: ProjectTrendsOptions = {},
): Promise<GitHubProjectTrendsResponse> {
  const params: Record<string, string | number | boolean> = { repos: repoIds.join(','), days }
  if (ranks) params.ranks = true
  const res = await api.get('/projects/github/trends', { params, signal })
  return normalizeProjectTrendsResponse(res.data, days)
}

// 提交链接只认 GitHub 上的页面，别的一律不摆成链接。
const GITHUB_PAGE = 'https://github.com/'

function normalizeProjectPeekCommit(data: any): GitHubProjectPeekCommit | null {
  const sha = typeof data?.sha === 'string' ? data.sha : ''
  const url = typeof data?.url === 'string' ? data.url : ''
  if (!sha || !url.startsWith(GITHUB_PAGE)) return null
  return {
    sha,
    message: typeof data?.message === 'string' ? data.message : '',
    author: typeof data?.author === 'string' ? data.author : '',
    committed_at: typeof data?.committed_at === 'string' ? data.committed_at : '',
    url,
  }
}

function normalizeProjectPeekResponse(data: any, repoId: string): GitHubProjectPeek {
  const readme: string[] = Array.isArray(data?.readme)
    ? data.readme.filter((paragraph: any) => typeof paragraph === 'string' && paragraph.trim())
    : []
  return {
    repo_id: typeof data?.repo_id === 'string' && data.repo_id ? data.repo_id : repoId,
    status: data?.status === 'ok' ? 'ok' : 'unavailable',
    has_readme: Boolean(data?.has_readme),
    readme,
    readme_more: Boolean(data?.readme_more),
    commit: normalizeProjectPeekCommit(data?.commit),
  }
}

/** 榜单悬停速览：README 开头几段与默认分支最近一次提交（服务端现读 GitHub 存半天）；不在公开项目库里的仓库 404。 */
export async function fetchProjectPeek(repoId: string, { signal }: { signal?: AbortSignal } = {}): Promise<GitHubProjectPeek> {
  const res = await api.get('/projects/github/peek', { params: { repo: repoId }, signal })
  return normalizeProjectPeekResponse(res.data, repoId)
}

export async function fetchMyProjectTags(
  source: ProjectSource = 'github',
): Promise<GitHubProjectTagsResponse> {
  const res = await api.get('/projects/me/tags', { params: { source } })
  const items = Array.isArray(res.data?.items)
    ? res.data.items
        .map((item: any) => {
          const value = String(item?.value ?? '').trim() || String(item?.label ?? '').trim()
          const origin = item?.tags_origin === 'user' ? 'user' : 'system'
          return {
            value,
            label: String(item?.label ?? '').trim() || value,
            label_zh: String(item?.label_zh ?? '').trim() || value,
            label_en: String(item?.label_en ?? '').trim() || value,
            count: Number(item?.count ?? 0),
            tags_origin: origin,
          } satisfies GitHubProjectTag
        })
        .filter((item: GitHubProjectTag) => item.value)
    : []
  return {
    items,
    total: Number(res.data?.total ?? items.length),
    source: res.data?.source ?? source,
  }
}

function normalizeToolWebsiteAddResponse(data: any, fallbackMessage: string): ToolWebsiteAddResponse {
  return {
    status: data?.status ?? 'succeeded',
    message: data?.message ?? fallbackMessage,
    duplicate: Boolean(data?.duplicate),
    item: data?.item ?? null,
  }
}

export async function favoriteProject(payload: ProjectFavoritePayload): Promise<ProjectFavoriteResponse> {
  const res = await api.post('/projects/me/favorites', payload)
  return {
    status: res.data?.status ?? 'succeeded',
    message: res.data?.message ?? i18n.global.t('projects.favoriteAddedPersonal'),
    source: res.data?.source ?? payload.source,
    repo_id: res.data?.repo_id ?? payload.repo_id ?? null,
    website_id: res.data?.website_id ?? payload.website_id ?? null,
    is_favorited: Boolean(res.data?.is_favorited ?? true),
    favorited_at: res.data?.favorited_at ?? null,
    deleted: Boolean(res.data?.deleted),
  }
}

export async function unfavoriteProject(payload: ProjectFavoritePayload): Promise<ProjectFavoriteResponse> {
  const params = payload.source === 'website'
    ? { source: payload.source, website_id: payload.website_id }
    : { source: payload.source, repo_id: payload.repo_id }
  const res = await api.delete('/projects/me/favorites', { params })
  return {
    status: res.data?.status ?? 'succeeded',
    message: res.data?.message ?? i18n.global.t('projects.favoriteRemovedPersonal'),
    source: res.data?.source ?? payload.source,
    repo_id: res.data?.repo_id ?? payload.repo_id ?? null,
    website_id: res.data?.website_id ?? payload.website_id ?? null,
    is_favorited: Boolean(res.data?.is_favorited),
    favorited_at: res.data?.favorited_at ?? null,
    deleted: Boolean(res.data?.deleted),
  }
}

function normalizeGitHubProjectRecommendResponse(
  data: any,
  payload: GitHubProjectRecommendPayload,
  fallbackMessage: string,
): GitHubProjectRecommendResponse {
  return {
    status: data?.status ?? 'succeeded',
    message: data?.message ?? fallbackMessage,
    repo_id: String(data?.repo_id ?? payload.repo_id ?? ''),
    full_name: String(data?.full_name ?? payload.full_name ?? ''),
    is_recommended: Boolean(data?.is_recommended),
    recommended_at: data?.recommended_at ?? null,
    removed: Boolean(data?.removed),
  }
}

export async function recommendGitHubProject(
  payload: GitHubProjectRecommendPayload,
): Promise<GitHubProjectRecommendResponse> {
  const res = await api.post('/ops/github-projects/recommendations', payload)
  return normalizeGitHubProjectRecommendResponse(res.data, payload, i18n.global.t('projects.recommendationAdded'))
}

export async function unrecommendGitHubProject(
  payload: GitHubProjectRecommendPayload,
): Promise<GitHubProjectRecommendResponse> {
  const res = await api.delete('/ops/github-projects/recommendations', { data: payload })
  return normalizeGitHubProjectRecommendResponse(res.data, payload, i18n.global.t('projects.recommendationRemoved'))
}

export async function fetchMyToolWebsiteQuota(): Promise<PersonalWebsiteQuota> {
  const res = await api.get('/projects/me/tool-websites/quota')
  const data = res.data ?? {}
  return {
    tier: data.tier === 'member' ? 'member' : 'free',
    unlimited: Boolean(data.unlimited),
    limit: data.limit == null ? null : Number(data.limit),
    used: Number(data.used ?? 0),
    remaining: data.remaining == null ? null : Number(data.remaining),
    window_seconds: Number(data.window_seconds ?? 86400),
    reset_at: data.reset_at ?? null,
  }
}

export async function addMyToolWebsite(url: string): Promise<ToolWebsiteAddResponse> {
  const res = await api.post('/projects/me/tool-websites', { url }, { timeout: TOOL_WEBSITE_ADD_TIMEOUT })
  return normalizeToolWebsiteAddResponse(res.data, i18n.global.t('projects.websiteAddedPersonal'))
}

export async function addMyToolWebsiteManual(
  payload: ManualToolWebsitePayload,
): Promise<ToolWebsiteAddResponse> {
  const res = await api.post('/projects/me/tool-websites/manual', payload, { timeout: TOOL_WEBSITE_ADD_TIMEOUT })
  return normalizeToolWebsiteAddResponse(res.data, i18n.global.t('projects.websiteAddedManual'))
}

function normalizeToolWebsiteDeleteResponse(data: any, websiteId: number | string, fallbackMessage: string): ToolWebsiteDeleteResponse {
  return {
    status: data?.status ?? 'succeeded',
    message: data?.message ?? fallbackMessage,
    deleted: Boolean(data?.deleted),
    website_id: Number(data?.website_id ?? websiteId),
  }
}

export async function removeMyToolWebsite(websiteId: number | string): Promise<ToolWebsiteDeleteResponse> {
  const res = await api.delete(`/projects/me/tool-websites/${websiteId}`)
  return normalizeToolWebsiteDeleteResponse(res.data, websiteId, i18n.global.t('projects.websiteRemoved'))
}

export async function updateMyToolWebsite(
  websiteId: number | string,
  payload: ToolWebsiteUpdatePayload,
): Promise<ToolWebsiteUpdateResponse> {
  const res = await api.patch(`/projects/me/tool-websites/${websiteId}`, payload)
  return {
    status: res.data?.status ?? 'succeeded',
    message: res.data?.message ?? i18n.global.t('projects.websiteUpdated'),
    item: res.data?.item ?? null,
  }
}

export async function fetchProjectTaxonomy(): Promise<ProjectTaxonomyResponse> {
  const res = await api.get('/projects/taxonomy')
  return {
    items: Array.isArray(res.data?.items) ? res.data.items : [],
  }
}
