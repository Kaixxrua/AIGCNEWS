/* eslint-disable @typescript-eslint/no-explicit-any -- API 边界 normalizer 基线：
   响应载荷先按 any 归一化再收窄到导出类型，随后端契约类型化逐步移除。 */
import { api } from '@/services/http/apiClient'

const TOOL_WEBSITE_ADD_TIMEOUT = 120_000

export type GitHubProjectSort = 'hot' | 'stars' | 'updated' | 'recent' | 'name'
export type ProjectSource = 'all' | 'github' | 'website'
export type ProjectViewSource = ProjectSource | 'favorites'
export type ProjectScope = 'all' | 'today' | 'recommended'

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
  daily_growth_source?: 'snapshot_delta' | 'github_trending_daily' | 'unavailable' | string | null
  daily_growth_observed_at?: string | null
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

export async function fetchGitHubProjects(params?: Omit<ProjectListParams, 'source' | 'scope'>): Promise<GitHubProjectsResponse> {
  return fetchProjects({ ...params, source: 'github', scope: 'all' })
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

export async function fetchMyProjectCategories(
  source: ProjectSource = 'all',
): Promise<GitHubProjectCategoriesResponse> {
  const res = await api.get('/projects/me/categories', { params: { source } })
  return normalizeProjectCategoriesResponse(res.data, source)
}

export async function fetchGitHubProjectCategories(): Promise<GitHubProjectCategoriesResponse> {
  return fetchProjectCategories('github')
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
    message: res.data?.message ?? '已加入我的收藏。',
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
    message: res.data?.message ?? '已取消收藏。',
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
  return normalizeGitHubProjectRecommendResponse(res.data, payload, '已加入站长推荐。')
}

export async function unrecommendGitHubProject(
  payload: GitHubProjectRecommendPayload,
): Promise<GitHubProjectRecommendResponse> {
  const res = await api.delete('/ops/github-projects/recommendations', { data: payload })
  return normalizeGitHubProjectRecommendResponse(res.data, payload, '已取消站长推荐。')
}

export async function addMyToolWebsite(url: string): Promise<ToolWebsiteAddResponse> {
  const res = await api.post('/projects/me/tool-websites', { url }, { timeout: TOOL_WEBSITE_ADD_TIMEOUT })
  return normalizeToolWebsiteAddResponse(res.data, '工具网站已加入我的收藏。')
}

export async function addMyToolWebsiteManual(
  payload: ManualToolWebsitePayload,
): Promise<ToolWebsiteAddResponse> {
  const res = await api.post('/projects/me/tool-websites/manual', payload, { timeout: TOOL_WEBSITE_ADD_TIMEOUT })
  return normalizeToolWebsiteAddResponse(res.data, '工具网站已手动加入我的收藏。')
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
  return normalizeToolWebsiteDeleteResponse(res.data, websiteId, '已移出我的收藏。')
}

export async function updateMyToolWebsite(
  websiteId: number | string,
  payload: ToolWebsiteUpdatePayload,
): Promise<ToolWebsiteUpdateResponse> {
  const res = await api.patch(`/projects/me/tool-websites/${websiteId}`, payload)
  return {
    status: res.data?.status ?? 'succeeded',
    message: res.data?.message ?? '网页收藏信息已更新。',
    item: res.data?.item ?? null,
  }
}

export async function fetchProjectTaxonomy(): Promise<ProjectTaxonomyResponse> {
  const res = await api.get('/projects/taxonomy')
  return {
    items: Array.isArray(res.data?.items) ? res.data.items : [],
  }
}
